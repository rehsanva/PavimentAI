import json

from fastapi import APIRouter, Depends

from ..db import get_conn

router = APIRouter(tags=["Áreas de atendimento"])


@router.get("/areas")
def listar_areas(conn=Depends(get_conn)):
    """Áreas onde é permitido registrar ocorrências, em GeoJSON (o front usa para
    centralizar o mapa e desenhar o contorno). O contorno vem levemente simplificado."""
    linhas = conn.execute(
        """
        SELECT id_area, nome, codigo_ibge,
               ST_AsGeoJSON(ST_SimplifyPreserveTopology(geometria::geometry, 0.0003), 5) AS geojson
        FROM areas_atendimento
        WHERE ativa
        ORDER BY nome
        """
    ).fetchall()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(l["geojson"]),
                "properties": {"id_area": l["id_area"], "nome": l["nome"], "codigo_ibge": l["codigo_ibge"]},
            }
            for l in linhas
        ],
    }
