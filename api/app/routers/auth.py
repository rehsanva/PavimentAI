import hmac
import secrets
import psycopg.errors
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import BackgroundTasks
 
from ..email_envio import enviar_email
from .. import auditoria, residencia
from ..config import settings
from ..db import get_conn
from ..deps import COLUNAS_USUARIO, usuario_atual
from ..schemas import CadastroIn, ReenviarIn, ResidenciaIn, TokenOut, UsuarioOut, VerificarEmailIn, AtualizarPerfilIn, ConfirmarSenhaIn, TrocarSenhaIn, EsqueciSenhaIn, RedefinirSenhaIn
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
    try:
        u = conn.execute(
            """
            INSERT INTO usuarios (nome, email, telefone, hash_senha)
            VALUES (%s, %s, %s, %s)
            RETURNING id_usuario, email
            """,
            (dados.nome, dados.email, dados.telefone, gerar_hash_senha(dados.senha)),
        ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "E-mail ou telefone já cadastrado")

    auditoria.registrar(conn, "cadastro", u["id_usuario"], "usuarios", u["id_usuario"])
    _criar_codigo_email(conn, u["id_usuario"], u["email"])
    return {"mensagem": "Conta criada. Confirme seu e-mail com o código enviado."}


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

def _confirmar_senha(conn, u, senha: str) -> None:
    """Pede a senha de novo nas ações sensíveis. Erros seguidos travam por um tempo,
    como no login: um token roubado não serve para adivinhar a senha."""
    falhas = conn.execute(
        """
        SELECT count(*) AS n FROM auditoria
        WHERE id_usuario = %s AND acao = 'senha_confirmacao_falha'
          AND criado_em > now() - make_interval(mins => %s)
        """,
        (u["id_usuario"], settings.bloqueio_login_min),
    ).fetchone()["n"]
    if falhas >= settings.max_falhas_login:
        raise HTTPException(
            429, f"Muitas tentativas erradas. Tente de novo em {settings.bloqueio_login_min} minutos.")
    atual = conn.execute(
        "SELECT hash_senha FROM usuarios WHERE id_usuario = %s", (u["id_usuario"],)
    ).fetchone()
    if not verificar_senha(senha, atual["hash_senha"]):
        auditoria.registrar(conn, "senha_confirmacao_falha", u["id_usuario"], "usuarios", u["id_usuario"])
        conn.commit()  # grava a falha mesmo devolvendo erro
        raise HTTPException(403, "Senha incorreta")


@router.patch("/me", response_model=UsuarioOut)
def atualizar_perfil(dados: AtualizarPerfilIn, u=Depends(usuario_atual), conn=Depends(get_conn)):
    """Troca nome e/ou telefone. O e-mail ainda não muda por aqui (exigiria confirmar o novo)."""
    if dados.telefone is not None and dados.telefone != u["telefone"] and u["telefone_verificado"]:
        raise HTTPException(409, "Telefone já verificado: a troca ainda não está disponível.")
    try:
        conn.execute(
            """
            UPDATE usuarios
            SET nome = COALESCE(%s::varchar, nome), telefone = COALESCE(%s::varchar, telefone)
            WHERE id_usuario = %s
            """,
            (dados.nome, dados.telefone, u["id_usuario"]),
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Este telefone já está cadastrado em outra conta.")
    auditoria.registrar(conn, "perfil_atualizado", u["id_usuario"], "usuarios", u["id_usuario"],
                        {"campos": [k for k, v in dados.model_dump().items() if v is not None]})
    return conn.execute(
        f"SELECT {COLUNAS_USUARIO} FROM usuarios WHERE id_usuario = %s", (u["id_usuario"],)
    ).fetchone()


@router.post("/me/senha")
def trocar_senha(dados: TrocarSenhaIn, u=Depends(usuario_atual), conn=Depends(get_conn)):
    _confirmar_senha(conn, u, dados.senha_atual)
    conn.execute(
        "UPDATE usuarios SET hash_senha = %s WHERE id_usuario = %s",
        (gerar_hash_senha(dados.senha_nova), u["id_usuario"]),
    )
    auditoria.registrar(conn, "senha_alterada", u["id_usuario"], "usuarios", u["id_usuario"])
    return {"mensagem": "Senha alterada."}


@router.delete("/me")
def excluir_conta(dados: ConfirmarSenhaIn, u=Depends(usuario_atual), conn=Depends(get_conn)):
    """Encerra a conta apagando os dados pessoais (anonimização). As ocorrências e fotos
    continuam no mapa, sem identificar a pessoa. Não tem volta."""
    if u["papel"] != "cidadao":
        raise HTTPException(403, "Contas de gestor e admin são encerradas pelo admin da plataforma.")
    _confirmar_senha(conn, u, dados.senha)
    conn.execute(
        "SELECT anonimizar_usuario(%s, %s)",
        (u["id_usuario"], gerar_hash_senha(secrets.token_urlsafe(32))),
    )
    auditoria.registrar(conn, "conta_anonimizada", u["id_usuario"], "usuarios", u["id_usuario"])
    return {"mensagem": "Conta encerrada. Seus dados pessoais foram apagados."}

@router.get("/eu", response_model=UsuarioOut)
def eu(u=Depends(usuario_atual)):
    """Devolve os dados de quem está logado (serve para testar o token)."""
    return u

# ------------------------------------------------------------ recuperação de senha
MAX_PEDIDOS_RECUPERACAO_HORA = 3
MSG_ESQUECI = (
    "Se este e-mail estiver cadastrado, enviamos um código para ele. "
    f"O código vale por {VALIDADE_CODIGO_MIN} minutos."
)
 
 
@router.post("/esqueci-senha")
def esqueci_senha(dados: EsqueciSenhaIn, tarefas: BackgroundTasks, conn=Depends(get_conn)):
    """Passo 1: manda um código de 6 dígitos por e-mail.
 
    A resposta é SEMPRE a mesma, exista a conta ou não, para não revelar
    quem tem cadastro (mesma ideia do /reenviar-codigo).
    """
    u = conn.execute(
        "SELECT id_usuario, nome, email, status_conta FROM usuarios WHERE email = lower(%s)",
        (dados.email,),
    ).fetchone()
    # Só conta ativa recupera senha: pendente confirma o e-mail primeiro,
    # e conta suspensa ou desativada não volta por aqui.
    if u is None or u["status_conta"] != "ativa":
        return {"mensagem": MSG_ESQUECI}
 
    # Freio contra abuso: no máximo 3 códigos por hora para a mesma conta
    recentes = conn.execute(
        """
        SELECT count(*) AS n FROM recuperacoes_senha
        WHERE id_usuario = %s AND criado_em > now() - interval '1 hour'
        """,
        (u["id_usuario"],),
    ).fetchone()["n"]
    if recentes >= MAX_PEDIDOS_RECUPERACAO_HORA:
        return {"mensagem": MSG_ESQUECI}
 
    codigo = gerar_codigo_6_digitos()
 
    # Só o código mais novo vale: os anteriores ainda abertos são encerrados
    conn.execute(
        "UPDATE recuperacoes_senha SET usado_em = now() WHERE id_usuario = %s AND usado_em IS NULL",
        (u["id_usuario"],),
    )
    r = conn.execute(
        """
        INSERT INTO recuperacoes_senha (id_usuario, hash_codigo, expira_em)
        VALUES (%s, %s, now() + make_interval(mins => %s))
        RETURNING id_recuperacao
        """,
        (u["id_usuario"], hash_codigo(u["id_usuario"], codigo), VALIDADE_CODIGO_MIN),
    ).fetchone()
    auditoria.registrar(
        conn, "recuperacao_solicitada", u["id_usuario"], "recuperacoes_senha", r["id_recuperacao"]
    )
 
    if settings.ambiente == "dev":
        # Em desenvolvimento o "e-mail" aparece aqui no terminal da API.
        print(f"\n[DEV] Código de recuperação de senha de {u['email']}: {codigo}\n", flush=True)
 
    texto = (
        f"Olá, {u['nome']}!\n\n"
        f"Seu código para criar uma nova senha no PavimentAI é: {codigo}\n\n"
        f"Ele vale por {VALIDADE_CODIGO_MIN} minutos. "
        "Se não foi você quem pediu, ignore este e-mail: sua senha continua a mesma.\n"
    )
    # Só envia de verdade se o SMTP estiver configurado no .env; roda depois da resposta
    tarefas.add_task(enviar_email, u["email"], "PavimentAI - recuperação de senha", texto)
    return {"mensagem": MSG_ESQUECI}
 
 
@router.post("/redefinir-senha")
def redefinir_senha(dados: RedefinirSenhaIn, conn=Depends(get_conn)):
    """Passo 2: confere o código recebido por e-mail e grava a senha nova."""
    erro = HTTPException(400, "Código inválido ou expirado. Peça um novo código.")
 
    u = conn.execute(
        "SELECT id_usuario, status_conta FROM usuarios WHERE email = lower(%s)",
        (dados.email,),
    ).fetchone()
    if u is None or u["status_conta"] != "ativa":
        raise erro
 
    # Só vale o código mais recente que ainda não foi usado nem venceu
    r = conn.execute(
        """
        SELECT id_recuperacao, hash_codigo, tentativas
        FROM recuperacoes_senha
        WHERE id_usuario = %s AND usado_em IS NULL AND expira_em > now()
        ORDER BY criado_em DESC
        LIMIT 1
        FOR UPDATE
        """,
        (u["id_usuario"],),
    ).fetchone()
    if r is None:
        raise erro
    if r["tentativas"] >= MAX_TENTATIVAS:
        raise HTTPException(429, "Muitas tentativas. Peça um novo código.")
 
    if not hmac.compare_digest(r["hash_codigo"], hash_codigo(u["id_usuario"], dados.codigo)):
        conn.execute(
            "UPDATE recuperacoes_senha SET tentativas = tentativas + 1 WHERE id_recuperacao = %s",
            (r["id_recuperacao"],),
        )
        conn.commit()  # grava a tentativa errada mesmo devolvendo erro (senão o rollback apagaria)
        raise erro
 
    conn.execute(
        "UPDATE usuarios SET hash_senha = %s WHERE id_usuario = %s",
        (gerar_hash_senha(dados.senha_nova), u["id_usuario"]),
    )
    conn.execute(
        "UPDATE recuperacoes_senha SET usado_em = now() WHERE id_recuperacao = %s",
        (r["id_recuperacao"],),
    )
    auditoria.registrar(conn, "senha_redefinida", u["id_usuario"], "usuarios", u["id_usuario"])
    return {"mensagem": "Senha alterada. Entre com a senha nova."}
 