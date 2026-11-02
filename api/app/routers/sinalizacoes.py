from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from .. import auditoria
from ..db import get_conn
from ..deps import usuario_atual
from ..schemas import SinalizacaoIn
from .ocorrencias import _checar_quem_pode_registrar

router = APIRouter(tags=["Sinalizações"])

IdBigint = Annotated[int, Path(ge=1, le=2**63 - 1)]
MAX_SINALIZACOES_HORA = 10


@router.post("/ocorrencias/{id_ocorrencia}/sinalizacoes", status_code=201)
def sinalizar(id_ocorrencia: IdBigint, dados: SinalizacaoIn, u=Depends(usuario_atual), conn=Depends(get_conn)):
    """O cidadão avisa que uma ocorrência está duplicada, no lugar errado, com informação errada
    ou que não é um problema. O gestor não precisa conferir tudo: ele analisa os avisos."""
    if u["papel"] != "cidadao":
        raise HTTPException(403, "Gestores resolvem direto pelo painel de gestão.")

    o = conn.execute(
        """
        SELECT o.id_ocorrencia, o.status, o.id_area, o.id_usuario_criador,
               coalesce((SELECT a.exige_residencia FROM areas_atendimento a
                          WHERE a.id_area = o.id_area), false) AS exige_residencia
        FROM ocorrencias o WHERE o.id_ocorrencia = %s
        """,
        (id_ocorrencia,),
    ).fetchone()
    if o is None:
        raise HTTPException(404, "Ocorrência não encontrada")
    if o["status"] != "aberta":
        raise HTTPException(409, "Só dá para sinalizar ocorrências abertas.")
    if o["id_usuario_criador"] == u["id_usuario"]:
        raise HTTPException(409, "Você não pode sinalizar a sua própria ocorrência.")
    # Mesmas regras de quem pode participar naquele município (residência, quando exigida)
    _checar_quem_pode_registrar(u, o["id_area"], o["exige_residencia"])

    if dados.motivo == "duplicidade":
        original = conn.execute(
            "SELECT id_area, status FROM ocorrencias WHERE id_ocorrencia = %s",
            (dados.id_ocorrencia_original,),
        ).fetchone()
        if (original is None or original["id_area"] != o["id_area"]
                or dados.id_ocorrencia_original == id_ocorrencia or original["status"] != "aberta"):
            raise HTTPException(422, "A ocorrência original precisa existir, estar aberta e ser do mesmo município.")

    n = conn.execute(
        "SELECT count(*) AS n FROM sinalizacoes WHERE id_usuario = %s AND criada_em > now() - interval '1 hour'",
        (u["id_usuario"],),
    ).fetchone()["n"]
    if n >= MAX_SINALIZACOES_HORA:
        raise HTTPException(429, "Muitas sinalizações em pouco tempo. Tente mais tarde.")

    ja = conn.execute(
        """
        SELECT 1 FROM sinalizacoes
        WHERE id_ocorrencia = %s AND id_usuario = %s AND motivo = %s AND status_analise = 'pendente'
        """,
        (id_ocorrencia, u["id_usuario"], dados.motivo),
    ).fetchone()
    if ja:
        raise HTTPException(409, "Você já fez essa sinalização e ela está aguardando análise.")

    s = conn.execute(
        """
        INSERT INTO sinalizacoes (id_ocorrencia, id_usuario, motivo, descricao, id_ocorrencia_original)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id_sinalizacao, status_analise, criada_em
        """,
        (id_ocorrencia, u["id_usuario"], dados.motivo, dados.descricao, dados.id_ocorrencia_original),
    ).fetchone()
    auditoria.registrar(conn, "sinalizacao_criada", u["id_usuario"], "sinalizacoes", s["id_sinalizacao"],
                        {"id_ocorrencia": id_ocorrencia, "motivo": dados.motivo})
    return s
