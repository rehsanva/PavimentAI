import hmac

import psycopg.errors
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from .. import auditoria, residencia
from ..config import settings
from ..db import get_conn
from ..deps import COLUNAS_USUARIO, usuario_atual
from ..schemas import CadastroIn, ReenviarIn, ResidenciaIn, TokenOut, UsuarioOut, VerificarEmailIn
from ..seguranca import (
    criar_token,
    gerar_codigo_6_digitos,
    gerar_hash_senha,
    hash_codigo,
    verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["Autenticação"])

MAX_TENTATIVAS = 5
VALIDADE_CODIGO_MIN = 15
INTERVALO_REENVIO_SEG = 60


def _criar_codigo_email(conn, id_usuario: int, email: str) -> None:
    codigo = gerar_codigo_6_digitos()
    conn.execute(
        """
        INSERT INTO verificacoes_contato (id_usuario, canal, token_hash, expira_em)
        VALUES (%s, 'email', %s, now() + make_interval(mins => %s))
        """,
        (id_usuario, hash_codigo(id_usuario, codigo), VALIDADE_CODIGO_MIN),
    )
    if settings.ambiente == "dev":
        # Em desenvolvimento o "e-mail" aparece aqui no terminal da API.
        print(f"\n[DEV] Código de verificação de {email}: {codigo}\n", flush=True)
    # TODO (produção): enviar o código por e-mail de verdade.


@router.post("/cadastro", status_code=201)
def cadastro(dados: CadastroIn, conn=Depends(get_conn)):
    # Primeiro descobre a cidade pelo CEP: se o CEP não existir, nem cria a conta
    res = residencia.resolver(conn, dados.cep)
    try:
        u = conn.execute(
            """
            INSERT INTO usuarios
                (nome, email, telefone, hash_senha, cep, codigo_ibge_residencia,
                 municipio_residencia, uf_residencia, id_area_residencia, residencia_atualizada_em)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            RETURNING id_usuario, email
            """,
            (dados.nome, dados.email, dados.telefone, gerar_hash_senha(dados.senha),
             res["cep"], res["codigo_ibge"], res["municipio"], res["uf"], res["id_area"]),
        ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "E-mail ou telefone já cadastrado")

    auditoria.registrar(conn, "cadastro", u["id_usuario"], "usuarios", u["id_usuario"])
    _criar_codigo_email(conn, u["id_usuario"], u["email"])
    resposta = {
        "mensagem": "Conta criada. Confirme seu e-mail com o código enviado.",
        "municipio": res["municipio"],
        "uf": res["uf"],
        "cidade_atendida": res["atendido"],
    }
    if not res["atendido"]:
        resposta["aviso"] = (f"{res['municipio']}/{res['uf']} ainda não é atendida pelo PavimentAI. "
                             "Você já pode criar a conta e acompanhar o mapa.")
    return resposta


@router.post("/verificar-email")
def verificar_email(dados: VerificarEmailIn, conn=Depends(get_conn)):
    erro = HTTPException(400, "Código inválido ou expirado")

    u = conn.execute(
        "SELECT id_usuario, status_conta FROM usuarios WHERE email = lower(%s)",
        (dados.email,),
    ).fetchone()
    if u is None or u["status_conta"] != "pendente":
        raise erro

    # Só vale o código mais recente que ainda não foi usado nem venceu
    v = conn.execute(
        """
        SELECT id_verificacao, token_hash, tentativas
        FROM verificacoes_contato
        WHERE id_usuario = %s AND canal = 'email'
          AND usado_em IS NULL AND expira_em > now()
        ORDER BY criado_em DESC
        LIMIT 1
        FOR UPDATE
        """,
        (u["id_usuario"],),
    ).fetchone()
    if v is None:
        raise erro
    if v["tentativas"] >= MAX_TENTATIVAS:
        raise HTTPException(429, "Muitas tentativas. Peça um novo código.")

    if not hmac.compare_digest(v["token_hash"], hash_codigo(u["id_usuario"], dados.codigo)):
        conn.execute(
            "UPDATE verificacoes_contato SET tentativas = tentativas + 1 WHERE id_verificacao = %s",
            (v["id_verificacao"],),
        )
        conn.commit()  # grava a tentativa errada mesmo devolvendo erro (senão o rollback apagaria)
        raise erro

    conn.execute(
        "UPDATE verificacoes_contato SET usado_em = now() WHERE id_verificacao = %s",
        (v["id_verificacao"],),
    )
    conn.execute(
        """
        UPDATE usuarios
        SET email_verificado = true, email_verificado_em = now(), status_conta = 'ativa'
        WHERE id_usuario = %s
        """,
        (u["id_usuario"],),
    )
    auditoria.registrar(conn, "email_verificado", u["id_usuario"], "usuarios", u["id_usuario"])
    return {"mensagem": "E-mail confirmado. Já pode fazer login."}


@router.post("/reenviar-codigo")
def reenviar_codigo(dados: ReenviarIn, conn=Depends(get_conn)):
    # Mesma resposta exista a conta ou não, para não revelar quem tem cadastro
    resposta = {"mensagem": "Se a conta existir e estiver pendente, um novo código foi enviado."}

    u = conn.execute(
        "SELECT id_usuario, email, status_conta FROM usuarios WHERE email = lower(%s)",
        (dados.email,),
    ).fetchone()
    if u is None or u["status_conta"] != "pendente":
        return resposta

    recente = conn.execute(
        """
        SELECT 1 FROM verificacoes_contato
        WHERE id_usuario = %s AND canal = 'email'
          AND criado_em > now() - make_interval(secs => %s)
        """,
        (u["id_usuario"], INTERVALO_REENVIO_SEG),
    ).fetchone()
    if recente:
        raise HTTPException(429, f"Aguarde {INTERVALO_REENVIO_SEG} segundos para pedir outro código")

    _criar_codigo_email(conn, u["id_usuario"], u["email"])
    return resposta


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), conn=Depends(get_conn)):
    # O formulário padrão do FastAPI chama o e-mail de "username"
    u = conn.execute(
        "SELECT id_usuario, hash_senha, status_conta FROM usuarios WHERE email = lower(%s)",
        (form.username,),
    ).fetchone()

    # Freio contra adivinhar senha: muitas senhas erradas seguidas travam a conta por um tempo
    if u:
        falhas = conn.execute(
            """
            SELECT count(*) AS n FROM auditoria f
            WHERE f.id_usuario = %(u)s AND f.acao = 'login_falha'
              AND f.criado_em > now() - make_interval(mins => %(min)s)
              AND f.criado_em > coalesce(
                    (SELECT max(l.criado_em) FROM auditoria l
                      WHERE l.id_usuario = %(u)s AND l.acao = 'login'), '-infinity'::timestamptz)
            """,
            {"u": u["id_usuario"], "min": settings.bloqueio_login_min},
        ).fetchone()["n"]
        if falhas >= settings.max_falhas_login:
            raise HTTPException(
                429, f"Muitas tentativas erradas. Tente de novo em {settings.bloqueio_login_min} minutos.")

    if not verificar_senha(form.password, u["hash_senha"] if u else None):
        if u:
            auditoria.registrar(conn, "login_falha", u["id_usuario"], "usuarios", u["id_usuario"])
            conn.commit()  # grava a falha mesmo devolvendo erro
        raise HTTPException(401, "E-mail ou senha incorretos",
                            headers={"WWW-Authenticate": "Bearer"})

    if u["status_conta"] == "pendente":
        raise HTTPException(403, "Confirme seu e-mail antes de entrar")
    if u["status_conta"] != "ativa":
        raise HTTPException(403, "Conta suspensa ou desativada")

    auditoria.registrar(conn, "login", u["id_usuario"], "usuarios", u["id_usuario"])
    return TokenOut(access_token=criar_token(u["id_usuario"]))


@router.put("/residencia", response_model=UsuarioOut)
def atualizar_residencia(dados: ResidenciaIn, u=Depends(usuario_atual), conn=Depends(get_conn)):
    """Informa (ou troca) o CEP de residência. Serve também para quem se cadastrou antes
    desta regra existir. Para ninguém pular de cidade só para registrar em outra,
    a troca só é permitida de tempos em tempos."""
    if u["papel"] != "cidadao":
        raise HTTPException(403, "Só cidadãos informam residência.")

    atual = conn.execute(
        """
        SELECT cep, (residencia_atualizada_em > now() - make_interval(days => %s)) AS recente
        FROM usuarios WHERE id_usuario = %s
        """,
        (settings.dias_troca_residencia, u["id_usuario"]),
    ).fetchone()
    if atual["cep"] is not None and atual["recente"]:
        raise HTTPException(
            429, f"Você só pode trocar a cidade de residência a cada {settings.dias_troca_residencia} dias.")

    res = residencia.resolver(conn, dados.cep)
    conn.execute(
        """
        UPDATE usuarios
        SET cep = %s, codigo_ibge_residencia = %s, municipio_residencia = %s,
            uf_residencia = %s, id_area_residencia = %s, residencia_atualizada_em = now()
        WHERE id_usuario = %s
        """,
        (res["cep"], res["codigo_ibge"], res["municipio"], res["uf"], res["id_area"], u["id_usuario"]),
    )
    auditoria.registrar(conn, "residencia_atualizada", u["id_usuario"], "usuarios", u["id_usuario"],
                        {"codigo_ibge": res["codigo_ibge"], "id_area": res["id_area"]})
    return conn.execute(
        f"SELECT {COLUNAS_USUARIO} FROM usuarios WHERE id_usuario = %s", (u["id_usuario"],)
    ).fetchone()


@router.get("/eu", response_model=UsuarioOut)
def eu(u=Depends(usuario_atual)):
    """Devolve os dados de quem está logado (serve para testar o token)."""
    return u
