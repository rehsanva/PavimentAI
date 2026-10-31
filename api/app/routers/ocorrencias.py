from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from .. import auditoria
from ..config import settings
from ..db import get_conn
from ..deps import usuario_atual
from ..schemas import OcorrenciaIn, OcorrenciaOut

router = APIRouter(prefix="/ocorrencias", tags=["Ocorrências"])

# Colunas devolvidas ao app. A gravidade mostrada é a verificada pelo gestor;
# se ainda não houver, a que o cidadão informou.
COLUNAS = """
    id_ocorrencia, tipo, categoria, descricao,
    COALESCE(gravidade_verificada, gravidade_cidadao) AS gravidade,
    latitude, longitude, status, canal_registro,
    criado_em, verificada_em, id_ocorrencia_principal
"""

MAX_GRAUS_MAPA = 10  # tamanho máximo da área pedida no mapa (em graus)


@router.post("", response_model=OcorrenciaOut, status_code=201)
def criar(dados: OcorrenciaIn, u=Depends(usuario_atual), conn=Depends(get_conn)):
    """Registra uma ocorrência. Se já houver uma aberta por perto, avisa (409)."""
    # 1) Freio contra spam: limite de registros por hora
    n = conn.execute(
        """
        SELECT count(*) AS n FROM ocorrencias
        WHERE id_usuario_criador = %s AND criado_em > now() - interval '1 hour'
        """,
        (u["id_usuario"],),
    ).fetchone()["n"]
    if n >= settings.limite_ocorrencias_hora:
        raise HTTPException(429, "Limite de registros por hora atingido. Tente mais tarde.")

    # 2) Duplicidade: mesma coisa (tipo e categoria), aberta, num raio de poucos metros
    if not dados.criar_mesmo_assim:
        proximas = conn.execute(
            """
            WITH p AS (
                SELECT ST_SetSRID(ST_MakePoint(%(lon)s::float8, %(lat)s::float8), 4326)::geography AS geo
            )
            SELECT o.id_ocorrencia, o.status, o.criado_em,
                   round(ST_Distance(o.localizacao, p.geo)::numeric, 1)::float8 AS distancia_m
            FROM ocorrencias o, p
            WHERE o.status = 'aberta'
              AND o.tipo = %(tipo)s
              AND o.categoria IS NOT DISTINCT FROM %(categoria)s::text
              AND ST_DWithin(o.localizacao, p.geo, %(raio)s::float8)
            ORDER BY distancia_m
            LIMIT 5
            """,
            {
                "lat": dados.latitude,
                "lon": dados.longitude,
                "tipo": dados.tipo,
                "categoria": dados.categoria,
                "raio": settings.raio_duplicidade_m,
            },
        ).fetchall()
        if proximas:
            raise HTTPException(
                409,
                detail={
                    "mensagem": "Já existe uma ocorrência parecida aberta por perto. "
                                "Envie criar_mesmo_assim=true para registrar assim mesmo.",
                    "proximas": [
                        {
                            "id_ocorrencia": p["id_ocorrencia"],
                            "distancia_m": p["distancia_m"],
                            "status": p["status"],
                            "criado_em": p["criado_em"].isoformat(),
                        }
                        for p in proximas
                    ],
                },
            )

    # 3) Grava a ocorrência, o primeiro item do histórico e a auditoria
    #    (tudo na mesma transação: ou grava tudo ou nada)
    canal = "app_cidadao" if u["papel"] == "cidadao" else "painel_gestao"
    o = conn.execute(
        f"""
        INSERT INTO ocorrencias
            (tipo, categoria, descricao, gravidade_cidadao,
             latitude, longitude, canal_registro, id_usuario_criador)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {COLUNAS}
        """,
        (dados.tipo, dados.categoria, dados.descricao, dados.gravidade,
         dados.latitude, dados.longitude, canal, u["id_usuario"]),
    ).fetchone()

    conn.execute(
        """
        INSERT INTO historico_status
            (id_ocorrencia, id_usuario, status_anterior, status_novo, justificativa)
        VALUES (%s, %s, NULL, 'aberta', 'Ocorrência registrada')
        """,
        (o["id_ocorrencia"], u["id_usuario"]),
    )
    auditoria.registrar(
        conn, "ocorrencia_criada", u["id_usuario"], "ocorrencias", o["id_ocorrencia"],
        {"tipo": dados.tipo, "ignorou_aviso_duplicidade": dados.criar_mesmo_assim},
    )
    return o


@router.get("/mapa")
def mapa(
    lat_min: Annotated[float, Query(ge=-90, le=90)],
    lat_max: Annotated[float, Query(ge=-90, le=90)],
    lon_min: Annotated[float, Query(ge=-180, le=180)],
    lon_max: Annotated[float, Query(ge=-180, le=180)],
    tipo: Literal["buraco", "acessibilidade"] | None = None,
    limite: Annotated[int, Query(ge=1, le=2000)] = 500,
    conn=Depends(get_conn),
):
    """Ocorrências abertas dentro de uma área, em GeoJSON (pronto para Leaflet/Mapbox)."""
    if lat_min >= lat_max or lon_min >= lon_max:
        raise HTTPException(422, "A área precisa ter lat_min < lat_max e lon_min < lon_max")
    if lat_max - lat_min > MAX_GRAUS_MAPA or lon_max - lon_min > MAX_GRAUS_MAPA:
        raise HTTPException(422, "Área muito grande. Dê mais zoom no mapa.")

    linhas = conn.execute(
        """
        SELECT id_ocorrencia, tipo, categoria, gravidade, status, canal_registro,
               confianca_max, criado_em, latitude, longitude
        FROM vw_mapa_ocorrencias
        WHERE ST_Intersects(
                  localizacao,
                  ST_MakeEnvelope(%(lon_min)s::float8, %(lat_min)s::float8,
                                  %(lon_max)s::float8, %(lat_max)s::float8, 4326)::geography)
          AND (%(tipo)s::text IS NULL OR tipo = %(tipo)s::text)
        ORDER BY criado_em DESC
        LIMIT %(limite)s
        """,
        {"lat_min": lat_min, "lat_max": lat_max, "lon_min": lon_min,
         "lon_max": lon_max, "tipo": tipo, "limite": limite},
    ).fetchall()

    return {
        "type": "FeatureCollection",
        "truncado": len(linhas) == limite,  # true = tem mais; dê zoom ou aumente o limite
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
                "properties": {
                    "id_ocorrencia": r["id_ocorrencia"],
                    "tipo": r["tipo"],
                    "categoria": r["categoria"],
                    "gravidade": r["gravidade"],
                    "status": r["status"],
                    "canal_registro": r["canal_registro"],
                    "confianca_ia": r["confianca_max"],
                    "criado_em": r["criado_em"],
                },
            }
            for r in linhas
        ],
    }


@router.get("/minhas", response_model=list[OcorrenciaOut])
def minhas(
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
    u=Depends(usuario_atual),
    conn=Depends(get_conn),
):
    """Ocorrências registradas por quem está logado (mais novas primeiro)."""
    return conn.execute(
        f"""
        SELECT {COLUNAS} FROM ocorrencias
        WHERE id_usuario_criador = %s
        ORDER BY criado_em DESC
        LIMIT %s OFFSET %s
        """,
        (u["id_usuario"], limite, deslocamento),
    ).fetchall()


# Esta rota fica por último: "/{id}" aceitaria qualquer coisa, inclusive "mapa" e "minhas"
@router.get("/{id_ocorrencia}", response_model=OcorrenciaOut)
def obter(id_ocorrencia: Annotated[int, Path(ge=1, le=2**63 - 1)], conn=Depends(get_conn)):
    o = conn.execute(
        f"SELECT {COLUNAS} FROM ocorrencias WHERE id_ocorrencia = %s",
        (id_ocorrencia,),
    ).fetchone()
    if o is None:
        raise HTTPException(404, "Ocorrência não encontrada")
    return o
