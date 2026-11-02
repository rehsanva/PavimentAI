import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from .. import auditoria, ibge
from ..db import get_conn_admin
from ..deps import exigir_papel
from ..schemas import AreaAlterarIn, AreaNovaIn, PapelIn

router = APIRouter(prefix="/admin", tags=["Admin"])

SoAdmin = exigir_papel("admin")
IdBigint = Annotated[int, Path(ge=1, le=2**63 - 1)]
Codigo = Annotated[str, Path(pattern=r"^\d{7}$")]

# MultiPolygon (válido, só polígonos) a partir do GeoJSON do IBGE
SQL_GEOM = "ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)), 3))"


@router.get("/municipios/buscar")
def buscar_municipio(
    uf: Annotated[str, Query(pattern=r"^[A-Za-z]{2}$", description="Sigla do estado, ex.: SP")],
    nome: Annotated[str, Query(min_length=2, max_length=60)],
    u=Depends(SoAdmin),
    conn=Depends(get_conn_admin),
):
    """Procura o município no IBGE pelo nome (aceita sem acento) e diz se já está cadastrado."""
    achados = ibge.buscar(uf, nome)
    ja = {}
    if achados:
        for l in conn.execute(
            "SELECT codigo_ibge, id_area, ativa FROM areas_atendimento WHERE codigo_ibge = ANY(%s)",
            ([a["codigo_ibge"] for a in achados],),
        ).fetchall():
            ja[l["codigo_ibge"]] = l
    return [
        {**a, "ja_cadastrada": a["codigo_ibge"] in ja,
         "id_area": ja[a["codigo_ibge"]]["id_area"] if a["codigo_ibge"] in ja else None,
         "ativa": ja[a["codigo_ibge"]]["ativa"] if a["codigo_ibge"] in ja else None}
        for a in achados
    ]


@router.get("/municipios/{codigo_ibge}/previa")
def previa_municipio(codigo_ibge: Codigo, u=Depends(SoAdmin), conn=Depends(get_conn_admin)):
    """Mostra o nome e o contorno ANTES de cadastrar (o painel desenha no mapa para o admin conferir)."""
    nome = ibge.nome_do_municipio(codigo_ibge)
    contorno = ibge.poligono(codigo_ibge)
    g = conn.execute(
        f"""
        WITH x AS (SELECT {SQL_GEOM} AS g)
        SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(g, 0.0003), 5)::jsonb AS contorno,
               ST_XMin(g) AS lon_min, ST_XMax(g) AS lon_max, ST_YMin(g) AS lat_min, ST_YMax(g) AS lat_max,
               ST_NPoints(g) AS pontos
        FROM x
        """,
        (json.dumps(contorno),),
    ).fetchone()
    ja = conn.execute("SELECT id_area FROM areas_atendimento WHERE codigo_ibge = %s", (codigo_ibge,)).fetchone()
    return {
        "codigo_ibge": codigo_ibge, "nome": nome, "ja_cadastrada": ja is not None,
        "id_area": ja["id_area"] if ja else None, "pontos": g["pontos"],
        "limites": {k: g[k] for k in ("lat_min", "lat_max", "lon_min", "lon_max")},
        "contorno": {"type": "Feature", "properties": {"nome": nome}, "geometry": g["contorno"]},
    }


@router.get("/areas")
def listar_areas(u=Depends(SoAdmin), conn=Depends(get_conn_admin)):
    """Todas as cidades cadastradas (inclusive desativadas), com números de cada uma."""
    return conn.execute(
        """
        SELECT a.id_area, a.nome, a.codigo_ibge, a.ativa, a.exige_residencia, a.criado_em,
               (SELECT count(*) FROM ocorrencias o WHERE o.id_area = a.id_area AND o.status = 'aberta') AS ocorrencias_abertas,
               (SELECT count(*) FROM ocorrencias o WHERE o.id_area = a.id_area) AS ocorrencias_total,
               (SELECT count(*) FROM usuarios g WHERE g.id_area_gestao = a.id_area) AS gestores,
               (SELECT count(*) FROM usuarios r WHERE r.id_area_residencia = a.id_area) AS moradores
        FROM areas_atendimento a ORDER BY a.nome
        """
    ).fetchall()


@router.post("/areas", status_code=201)
def cadastrar_area(dados: AreaNovaIn, u=Depends(SoAdmin), conn=Depends(get_conn_admin)):
    """Cadastra uma cidade nova: baixa o nome e o contorno oficial no IBGE e já liga
    as ocorrências e os moradores que existiam nela."""
    if conn.execute("SELECT 1 FROM areas_atendimento WHERE codigo_ibge = %s", (dados.codigo_ibge,)).fetchone():
        raise HTTPException(409, "Esta cidade já está cadastrada. Use a alteração (PATCH) para reativar ou mudar.")
    nome = ibge.nome_do_municipio(dados.codigo_ibge)
    contorno = ibge.poligono(dados.codigo_ibge)

    a = conn.execute(
        f"""
        INSERT INTO areas_atendimento (nome, codigo_ibge, geometria, exige_residencia)
        VALUES (%s, %s, ({SQL_GEOM})::geography, %s)
        RETURNING id_area, nome, codigo_ibge, ativa, exige_residencia, criado_em
        """,
        (nome, dados.codigo_ibge, json.dumps(contorno), dados.exige_residencia),
    ).fetchone()
    ocorrencias = conn.execute(
        """
        UPDATE ocorrencias o SET id_area = a.id_area FROM areas_atendimento a
        WHERE a.id_area = %s AND o.id_area IS NULL AND ST_DWithin(a.geometria, o.localizacao, 30)
        """,
        (a["id_area"],),
    ).rowcount
    moradores = conn.execute(
        """
        UPDATE usuarios u SET id_area_residencia = a.id_area FROM areas_atendimento a
        WHERE a.id_area = %s AND u.codigo_ibge_residencia = a.codigo_ibge AND u.id_area_residencia IS NULL
        """,
        (a["id_area"],),
    ).rowcount
    auditoria.registrar(conn, "area_cadastrada", u["id_usuario"], "areas_atendimento", a["id_area"],
                        {"codigo_ibge": dados.codigo_ibge, "nome": nome,
                         "exige_residencia": dados.exige_residencia})
    return {**a, "ocorrencias_ligadas": ocorrencias, "moradores_ligados": moradores}


@router.patch("/areas/{id_area}")
def alterar_area(id_area: IdBigint, dados: AreaAlterarIn, u=Depends(SoAdmin), conn=Depends(get_conn_admin)):
    """Ativar/desativar a cidade, ligar/desligar a regra de "só moradores" ou corrigir o nome."""
    a = conn.execute(
        """
        UPDATE areas_atendimento
        SET ativa = COALESCE(%s::boolean, ativa),
            exige_residencia = COALESCE(%s::boolean, exige_residencia),
            nome = COALESCE(%s::varchar, nome)
        WHERE id_area = %s
        RETURNING id_area, nome, codigo_ibge, ativa, exige_residencia
        """,
        (dados.ativa, dados.exige_residencia, dados.nome, id_area),
    ).fetchone()
    if a is None:
        raise HTTPException(404, "Cidade não encontrada.")
    auditoria.registrar(conn, "area_alterada", u["id_usuario"], "areas_atendimento", id_area,
                        dados.model_dump(exclude_none=True))
    return a


@router.get("/usuarios")
def listar_usuarios(
    papel: Literal["cidadao", "gestor", "admin"] | None = None,
    id_area_gestao: Annotated[int | None, Query(ge=1)] = None,
    busca: Annotated[str | None, Query(min_length=2, max_length=60, description="Parte do nome ou do e-mail")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
    u=Depends(SoAdmin),
    conn=Depends(get_conn_admin),
):
    """Procura usuários para o admin promover a gestor. Nunca mostra senha."""
    linhas = conn.execute(
        """
        SELECT x.id_usuario, x.nome, x.email, x.papel, x.status_conta, x.id_area_gestao,
               g.nome AS cidade_gestao, r.nome AS cidade_residencia, count(*) OVER () AS total
        FROM usuarios x
        LEFT JOIN areas_atendimento g ON g.id_area = x.id_area_gestao
        LEFT JOIN areas_atendimento r ON r.id_area = x.id_area_residencia
        WHERE (%(papel)s::text IS NULL OR x.papel = %(papel)s::text)
          AND (%(area)s::int IS NULL OR x.id_area_gestao = %(area)s::int)
          AND (%(busca)s::text IS NULL OR x.nome ILIKE '%%' || %(busca)s::text || '%%'
                                       OR x.email ILIKE '%%' || %(busca)s::text || '%%')
        ORDER BY x.nome
        LIMIT %(limite)s OFFSET %(desloc)s
        """,
        {"papel": papel, "area": id_area_gestao, "busca": busca, "limite": limite, "desloc": deslocamento},
    ).fetchall()
    total = linhas[0]["total"] if linhas else 0
    return {"total": total, "itens": [{k: v for k, v in l.items() if k != "total"} for l in linhas]}


@router.post("/usuarios/{id_usuario}/papel")
def mudar_papel(id_usuario: IdBigint, dados: PapelIn, u=Depends(SoAdmin), conn=Depends(get_conn_admin)):
    """Promove alguém a gestor de uma cidade, faz admin, ou volta a cidadão."""
    if id_usuario == u["id_usuario"]:
        raise HTTPException(409, "Você não pode mudar o seu próprio papel.")
    alvo = conn.execute(
        "SELECT id_usuario, papel, status_conta FROM usuarios WHERE id_usuario = %s FOR UPDATE",
        (id_usuario,),
    ).fetchone()
    if alvo is None:
        raise HTTPException(404, "Usuário não encontrado.")
    if alvo["status_conta"] != "ativa":
        raise HTTPException(409, "A conta precisa estar ativa (e-mail confirmado).")
    if dados.papel == "gestor":
        area = conn.execute(
            "SELECT ativa FROM areas_atendimento WHERE id_area = %s", (dados.id_area_gestao,)
        ).fetchone()
        if area is None or not area["ativa"]:
            raise HTTPException(422, "A cidade do gestor precisa existir e estar ativa.")

    novo = conn.execute(
        """
        UPDATE usuarios SET papel = %s, id_area_gestao = %s WHERE id_usuario = %s
        RETURNING id_usuario, nome, email, papel, id_area_gestao
        """,
        (dados.papel, dados.id_area_gestao, id_usuario),
    ).fetchone()
    auditoria.registrar(conn, "papel_alterado", u["id_usuario"], "usuarios", id_usuario,
                        {"de": alvo["papel"], "para": dados.papel, "id_area_gestao": dados.id_area_gestao})
    return novo
