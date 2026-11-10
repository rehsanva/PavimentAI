
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from .. import auditoria
from ..db import get_conn
from ..deps import exigir_gestao_da_area, exigir_papel
from ..schemas import AnaliseIn, MudarStatusIn, OcorrenciaOut, TriagemIn
from .ocorrencias import COLUNAS

router = APIRouter(prefix="/gestao", tags=["Gestão"])

IdBigint = Annotated[int, Path(ge=1, le=2**63 - 1)]
Gestao = exigir_papel("gestor", "admin")

# Gravidade que o painel mostra: a confirmada pelo gestor; senão a do cidadão; senão a da IA
LATERAL_IA = """
    LEFT JOIN LATERAL (
        SELECT (ARRAY_AGG(d.gravidade_estimada ORDER BY
                   CASE d.gravidade_estimada WHEN 'grave' THEN 3 WHEN 'moderado' THEN 2
                                             WHEN 'leve' THEN 1 ELSE 0 END DESC))[1] AS gravidade_ia,
               MAX(d.confianca) AS confianca_max
        FROM deteccoes_ia d WHERE d.id_ocorrencia = o.id_ocorrencia
    ) ia ON true
"""

# Ordens fixas (nunca montamos o ORDER BY com texto vindo do usuário)
ORDENS = {
    "prioridade": "CASE gravidade WHEN 'grave' THEN 3 WHEN 'moderado' THEN 2 WHEN 'leve' THEN 1 ELSE 0 END DESC, "
                  "sinalizacoes_pendentes DESC, criado_em ASC",
    "recentes": "criado_em DESC",
    "antigas": "criado_em ASC",
}

def _escopo(u, id_area: int | None) -> int | None:
    """Isolamento: gestor enxerga SEMPRE só a própria cidade. Admin escolhe (ou vê todas)."""
    if u["papel"] == "gestor":
        if u["id_area_gestao"] is None:
            raise HTTPException(403, "Seu usuário de gestor ainda não está ligado a um município.")
        if id_area is not None and id_area != u["id_area_gestao"]:
            raise HTTPException(403, "Você só acessa o seu município.")
        return u["id_area_gestao"]
    return id_area

@router.get("/resumo")
def resumo(
    id_area: Annotated[int | None, Query(ge=1, description="Só para admin")] = None,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Números para o painel: quantas ocorrências por status, tipo e gravidade."""
    area = _escopo(u, id_area)

    por_status = conn.execute(
        "SELECT status, count(*) AS n FROM ocorrencias "
        "WHERE (%(a)s::int IS NULL OR id_area = %(a)s::int) GROUP BY status",
        {"a": area},
    ).fetchall()

    abertas = conn.execute(
        """
        SELECT tipo, coalesce(gravidade_verificada, gravidade_cidadao) AS gravidade, count(*) AS n
        FROM ocorrencias
        WHERE status = 'aberta' AND (%(a)s::int IS NULL OR id_area = %(a)s::int)
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        {"a": area},
    ).fetchall()

    pendentes = conn.execute(
        """
        SELECT count(*) AS n FROM sinalizacoes s
        JOIN ocorrencias o ON o.id_ocorrencia = s.id_ocorrencia
        WHERE s.status_analise = 'pendente' AND (%(a)s::int IS NULL OR o.id_area = %(a)s::int)
        """,
        {"a": area},
    ).fetchone()["n"]

    return {
        "id_area": area,
        "por_status": {l["status"]: l["n"] for l in por_status},
        "abertas_por_tipo_e_gravidade": abertas,
        "sinalizacoes_pendentes": pendentes,
    }

@router.get("/ocorrencias")
def listar(
    status: Literal["aberta", "resolvida", "descartada", "duplicada", "todas"] = "aberta",
    tipo: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,19}$")] = None,
    gravidade: Literal["leve", "moderado", "grave"] | None = None,
    ordenar: Literal["prioridade", "recentes", "antigas"] = "prioridade",
    id_area: Annotated[int | None, Query(ge=1, description="Só para admin")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Fila de trabalho da cidade. Por padrão: abertas, as mais graves e antigas primeiro."""
    area = _escopo(u, id_area)

    linhas = conn.execute(
        f"""
        WITH base AS (
            SELECT o.id_ocorrencia, o.tipo, o.categoria, o.descricao, o.status,
                   o.latitude, o.longitude, o.criado_em, o.verificada_em, o.id_area,
                   COALESCE(o.gravidade_verificada, o.gravidade_cidadao, ia.gravidade_ia) AS gravidade,
                   ia.confianca_max AS confianca_ia,
                   (SELECT count(*) FROM ocorrencia_midias om
                     WHERE om.id_ocorrencia = o.id_ocorrencia) AS qtd_fotos,
                   (SELECT count(*) FROM sinalizacoes s
                     WHERE s.id_ocorrencia = o.id_ocorrencia AND s.status_analise = 'pendente')
                       AS sinalizacoes_pendentes
            FROM ocorrencias o
            {LATERAL_IA}
            WHERE (%(area)s::int IS NULL OR o.id_area = %(area)s::int)
              AND (%(status)s::text IS NULL OR o.status = %(status)s::text)
              AND (%(tipo)s::text IS NULL OR o.tipo = %(tipo)s::text)
        )
        SELECT *, count(*) OVER () AS total FROM base
        WHERE (%(gravidade)s::text IS NULL OR gravidade = %(gravidade)s::text)
        ORDER BY {ORDENS[ordenar]}
        LIMIT %(limite)s OFFSET %(desloc)s
        """,
        {
            "area": area,
            "status": None if status == "todas" else status,
            "tipo": tipo,
            "gravidade": gravidade,
            "limite": limite,
            "desloc": deslocamento,
        },
    ).fetchall()

    total = linhas[0]["total"] if linhas else 0

    return {
        "total": total,
        "itens": [{k: v for k, v in l.items() if k != "total"} for l in linhas],
    }

@router.get("/ocorrencias/{id_ocorrencia}")
def detalhe(id_ocorrencia: IdBigint, u=Depends(Gestao), conn=Depends(get_conn)):
    """Tudo sobre uma ocorrência: fotos, detecções da IA, histórico e sinalizações."""
    o = conn.execute(
        """
        SELECT o.id_ocorrencia, o.tipo, o.categoria, o.descricao, o.status, o.canal_registro,
               o.gravidade_cidadao, o.gravidade_verificada, o.latitude, o.longitude,
               o.criado_em, o.verificada_em, o.id_area, o.id_ocorrencia_principal,
               o.situacao_ia, o.triagem_decisao, o.triagem_em, o.triagem_motivo,
               o.id_usuario_criador, c.nome AS criador_nome,
               o.id_gestor_verificador, g.nome AS verificador_nome
        FROM ocorrencias o
        LEFT JOIN usuarios c ON c.id_usuario = o.id_usuario_criador
        LEFT JOIN usuarios g ON g.id_usuario = o.id_gestor_verificador
        WHERE o.id_ocorrencia = %s
        """,
        (id_ocorrencia,),
    ).fetchone()

    if o is None:
        raise HTTPException(404, "Ocorrência não encontrada")

    exigir_gestao_da_area(u, o["id_area"])

    fotos = conn.execute(
        """
        SELECT m.id_midia, m.origem, om.finalidade, m.largura_pixels, m.altura_pixels, m.enviada_em
        FROM ocorrencia_midias om JOIN midias m ON m.id_midia = om.id_midia
        WHERE om.id_ocorrencia = %s ORDER BY m.enviada_em, m.id_midia
        """,
        (id_ocorrencia,),
    ).fetchall()

    historico = conn.execute(
        """
        SELECT h.status_anterior, h.status_novo, h.justificativa, h.alterado_em, us.nome AS por
        FROM historico_status h LEFT JOIN usuarios us ON us.id_usuario = h.id_usuario
        WHERE h.id_ocorrencia = %s ORDER BY h.alterado_em DESC, h.id_historico DESC
        """,
        (id_ocorrencia,),
    ).fetchall()

    deteccoes = conn.execute(
        """
        SELECT id_deteccao, id_midia, classe_detectada, confianca, bbox_x, bbox_y,
               bbox_largura, bbox_altura, gravidade_estimada, versao_modelo, processada_em
        FROM deteccoes_ia WHERE id_ocorrencia = %s ORDER BY confianca DESC
        """,
        (id_ocorrencia,),
    ).fetchall()

    sinalizacoes = conn.execute(
        """
        SELECT id_sinalizacao, motivo, descricao, status_analise, id_ocorrencia_original,
               criada_em, analisada_em
        FROM sinalizacoes WHERE id_ocorrencia = %s ORDER BY criada_em DESC
        """,
        (id_ocorrencia,),
    ).fetchall()

    return {
        **o,
        "fotos": [{**f, "url": f"/midias/{f['id_midia']}/arquivo"} for f in fotos],
        "historico": historico,
        "deteccoes_ia": deteccoes,
        "sinalizacoes": sinalizacoes,
    }

@router.post("/ocorrencias/{id_ocorrencia}/status", response_model=OcorrenciaOut)
def mudar_status(
    id_ocorrencia: IdBigint,
    dados: MudarStatusIn,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Resolver, descartar, marcar como duplicada ou reabrir. Também confirma a gravidade.

    Regras: de "aberta" vai para resolvida, descartada ou duplicada. Para mudar de novo,
    primeiro reabre (status=aberta). Tudo fica no histórico."""

    o = conn.execute(
        "SELECT id_ocorrencia, tipo, status, id_area FROM ocorrencias WHERE id_ocorrencia = %s FOR UPDATE",
        (id_ocorrencia,),
    ).fetchone()

    if o is None:
        raise HTTPException(404, "Ocorrência não encontrada")

    exigir_gestao_da_area(u, o["id_area"])

    atual = o["status"]
    mudou = dados.status != atual

    if not mudou and dados.gravidade_verificada is None:
        raise HTTPException(409, "A ocorrência já está nesse status.")

    if mudou and atual != "aberta" and dados.status != "aberta":
        raise HTTPException(409, "Para mudar o status, primeiro reabra a ocorrência (status=aberta).")

    # Verifica na tabela de tipos se a ocorrência permite gravidade
    if dados.gravidade_verificada is not None:
        usa = conn.execute(
            "SELECT usa_gravidade FROM tipos_ocorrencia WHERE codigo = %s",
            (o["tipo"],),
        ).fetchone()

        if usa is None:
            raise HTTPException(500, "Tipo de ocorrência não cadastrado.")

        if not usa["usa_gravidade"]:
            raise HTTPException(
                422,
                "Gravidade não se aplica a este tipo de ocorrência."
            )

    if dados.status == "duplicada":
        p = conn.execute(
            "SELECT id_ocorrencia, status, id_area FROM ocorrencias WHERE id_ocorrencia = %s",
            (dados.id_ocorrencia_principal,),
        ).fetchone()

        if p is None or p["id_area"] != o["id_area"] or p["id_ocorrencia"] == id_ocorrencia:
            raise HTTPException(422, "A ocorrência principal precisa existir, ser outra e ser do mesmo município.")

        if p["status"] == "duplicada":
            raise HTTPException(422, "A ocorrência principal não pode ser, ela mesma, uma duplicada.")

    nova = conn.execute(
        f"""
        UPDATE ocorrencias
        SET status = %s,
            id_ocorrencia_principal = %s,
            gravidade_verificada = COALESCE(%s::varchar, gravidade_verificada),
            id_gestor_verificador = %s,
            verificada_em = now()
        WHERE id_ocorrencia = %s
        RETURNING {COLUNAS}
        """,
        (
            dados.status,
            dados.id_ocorrencia_principal,
            dados.gravidade_verificada,
            u["id_usuario"],
            id_ocorrencia,
        ),
    ).fetchone()

    if mudou:
        conn.execute(
            """
            INSERT INTO historico_status
                (id_ocorrencia, id_usuario, status_anterior, status_novo, justificativa)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                id_ocorrencia,
                u["id_usuario"],
                atual,
                dados.status,
                dados.justificativa,
            ),
        )

    auditoria.registrar(
        conn,
        "ocorrencia_status_alterado" if mudou else "ocorrencia_gravidade_confirmada",
        u["id_usuario"],
        "ocorrencias",
        id_ocorrencia,
        {
            "de": atual,
            "para": dados.status,
            "gravidade_verificada": dados.gravidade_verificada,
            "principal": dados.id_ocorrencia_principal,
        },
    )

    return nova

@router.get("/sinalizacoes")
def listar_sinalizacoes(
    status_analise: Literal["pendente", "aceita", "rejeitada", "todas"] = "pendente",
    id_area: Annotated[int | None, Query(ge=1, description="Só para admin")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Avisos dos cidadãos sobre ocorrências (duplicada, local errado, não é um problema...)."""
    area = _escopo(u, id_area)

    linhas = conn.execute(
        """
        SELECT s.id_sinalizacao, s.motivo, s.descricao, s.status_analise, s.criada_em, s.analisada_em,
               s.id_ocorrencia_original, o.id_ocorrencia, o.tipo, o.categoria,
               o.status AS status_ocorrencia, o.id_area,
               count(*) OVER () AS total
        FROM sinalizacoes s
        JOIN ocorrencias o ON o.id_ocorrencia = s.id_ocorrencia
        WHERE (%(area)s::int IS NULL OR o.id_area = %(area)s::int)
          AND (%(st)s::text IS NULL OR s.status_analise = %(st)s::text)
        ORDER BY s.criada_em ASC
        LIMIT %(limite)s OFFSET %(desloc)s
        """,
        {
            "area": area,
            "st": None if status_analise == "todas" else status_analise,
            "limite": limite,
            "desloc": deslocamento,
        },
    ).fetchall()

    total = linhas[0]["total"] if linhas else 0

    return {
        "total": total,
        "itens": [{k: v for k, v in l.items() if k != "total"} for l in linhas],
    }

@router.post("/sinalizacoes/{id_sinalizacao}/analisar")
def analisar_sinalizacao(
    id_sinalizacao: IdBigint,
    dados: AnaliseIn,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Aceita ou rejeita a sinalização. Se aceitar, mude o status da ocorrência pela rota de status."""

    s = conn.execute(
        """
        SELECT s.id_sinalizacao, s.status_analise, s.id_ocorrencia, o.id_area
        FROM sinalizacoes s JOIN ocorrencias o ON o.id_ocorrencia = s.id_ocorrencia
        WHERE s.id_sinalizacao = %s FOR UPDATE OF s
        """,
        (id_sinalizacao,),
    ).fetchone()

    if s is None:
        raise HTTPException(404, "Sinalização não encontrada")

    exigir_gestao_da_area(u, s["id_area"])

    if s["status_analise"] != "pendente":
        raise HTTPException(409, "Esta sinalização já foi analisada.")

    nova = conn.execute(
        """
        UPDATE sinalizacoes
        SET status_analise = %s, id_gestor_analista = %s, analisada_em = now()
        WHERE id_sinalizacao = %s
        RETURNING id_sinalizacao, id_ocorrencia, status_analise, analisada_em
        """,
        (dados.resultado, u["id_usuario"], id_sinalizacao),
    ).fetchone()

    auditoria.registrar(
        conn,
        "sinalizacao_analisada",
        u["id_usuario"],
        "sinalizacoes",
        id_sinalizacao,
        {"resultado": dados.resultado, "id_ocorrencia": s["id_ocorrencia"]},
    )

    return nova

@router.get("/triagem")
def fila_triagem(
    id_area: Annotated[int | None, Query(ge=1, description="Só para admin")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Ocorrências em que a IA ficou na dúvida (confiança entre 0,25 e 0,60), esperando o gestor.
    As mais antigas primeiro."""
    area = _escopo(u, id_area)

    linhas = conn.execute(
        f"""
        SELECT o.id_ocorrencia, o.tipo, o.descricao, o.latitude, o.longitude,
               o.criado_em, o.id_area, ia.gravidade_ia, ia.confianca_max,
               (SELECT count(*) FROM deteccoes_ia d
                 WHERE d.id_ocorrencia = o.id_ocorrencia) AS qtd_caixas,
               (SELECT count(*) FROM ocorrencia_midias om
                 WHERE om.id_ocorrencia = o.id_ocorrencia) AS qtd_fotos,
               count(*) OVER () AS total
        FROM ocorrencias o
        {LATERAL_IA}
        WHERE o.status = 'aberta' AND o.situacao_ia = 'triagem' AND o.triagem_decisao IS NULL
          AND (%(area)s::int IS NULL OR o.id_area = %(area)s::int)
        ORDER BY o.criado_em ASC
        LIMIT %(limite)s OFFSET %(desloc)s
        """,
        {"area": area, "limite": limite, "desloc": deslocamento},
    ).fetchall()

    total = linhas[0]["total"] if linhas else 0

    return {
        "total": total,
        "itens": [{k: v for k, v in l.items() if k != "total"} for l in linhas],
    }

@router.post("/ocorrencias/{id_ocorrencia}/triagem")
def decidir_triagem(
    id_ocorrencia: IdBigint,
    dados: TriagemIn,
    u=Depends(Gestao),
    conn=Depends(get_conn),
):
    """Aprova (a ocorrência vai para o mapa) ou recusa (fica descartada, com o motivo no histórico)."""

    o = conn.execute(
        """
        SELECT id_ocorrencia, status, id_area, situacao_ia, triagem_decisao
        FROM ocorrencias WHERE id_ocorrencia = %s FOR UPDATE
        """,
        (id_ocorrencia,),
    ).fetchone()

    if o is None:
        raise HTTPException(404, "Ocorrência não encontrada")

    exigir_gestao_da_area(u, o["id_area"])

    if o["status"] != "aberta" or o["situacao_ia"] != "triagem" or o["triagem_decisao"] is not None:
        raise HTTPException(409, "Esta ocorrência não está aguardando triagem.")

    novo_status = "aberta" if dados.decisao == "aprovada" else "descartada"

    conn.execute(
        """
        UPDATE ocorrencias
        SET triagem_decisao = %s, triagem_por = %s, triagem_em = now(), triagem_motivo = %s,
            status = %s,
            gravidade_verificada = COALESCE(%s::varchar, gravidade_verificada),
            id_gestor_verificador = %s, verificada_em = now()
        WHERE id_ocorrencia = %s
        """,
        (
            dados.decisao,
            u["id_usuario"],
            dados.motivo,
            novo_status,
            dados.gravidade_verificada,
            u["id_usuario"],
            id_ocorrencia,
        ),
    )

    if novo_status != o["status"]:
        conn.execute(
            """
            INSERT INTO historico_status
                (id_ocorrencia, id_usuario, status_anterior, status_novo, justificativa)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                id_ocorrencia,
                u["id_usuario"],
                o["status"],
                novo_status,
                f"Recusada na triagem: {dados.motivo}",
            ),
        )

    auditoria.registrar(
        conn,
        "triagem_decidida",
        u["id_usuario"],
        "ocorrencias",
        id_ocorrencia,
        {
            "decisao": dados.decisao,
            "gravidade_verificada": dados.gravidade_verificada,
        },
    )

    return {
        "id_ocorrencia": id_ocorrencia,
        "decisao": dados.decisao,
        "status": novo_status,
    }