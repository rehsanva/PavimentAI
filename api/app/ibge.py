"""Conversa com a API pública do IBGE: buscar município pelo nome e baixar o contorno."""
import gzip
import json
import re
import unicodedata
import urllib.error
import urllib.request
from functools import lru_cache

from fastapi import HTTPException

from .config import settings

VARIANTES_MALHA = [
    "?formato=application/vnd.geo+json&qualidade=maxima",
    "?formato=application/vnd.geo+json&qualidade=4",
    "?formato=application/vnd.geo+json",
]


def _pedir(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "PavimentAI/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resposta:
        corpo = resposta.read()
        # O IBGE às vezes responde compactado (gzip)
        if resposta.headers.get("Content-Encoding", "").lower() == "gzip" or corpo[:2] == b"\x1f\x8b":
            corpo = gzip.decompress(corpo)
    return json.loads(corpo.decode("utf-8"))


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower().strip()


def _base() -> str:
    return settings.ibge_api_url.rstrip("/")


@lru_cache(maxsize=32)
def _municipios_da_uf(uf: str) -> tuple:
    try:
        dados = _pedir(f"{_base()}/v1/localidades/estados/{uf}/municipios")
    except (OSError, ValueError):
        raise HTTPException(502, "Não consegui consultar o IBGE agora. Tente de novo em instantes.")
    return tuple((str(m["id"]), m["nome"]) for m in dados if isinstance(m, dict) and "id" in m)


def buscar(uf: str, nome: str, limite: int = 20) -> list[dict]:
    """Municípios da UF cujo nome contém o texto (sem diferenciar acento nem maiúscula)."""
    termo = sem_acento(nome)
    achados = [(c, n) for c, n in _municipios_da_uf(uf.upper()) if termo in sem_acento(n)]
    achados.sort(key=lambda x: (not sem_acento(x[1]).startswith(termo), x[1]))
    return [{"codigo_ibge": c, "nome": n, "uf": uf.upper()} for c, n in achados[:limite]]


def nome_do_municipio(codigo: str) -> str:
    try:
        dados = _pedir(f"{_base()}/v1/localidades/municipios/{codigo}")
    except urllib.error.HTTPError as erro:
        if erro.code in (400, 404):
            raise HTTPException(404, "Esse código não existe no IBGE.")
        raise HTTPException(502, "Não consegui consultar o IBGE agora. Tente de novo em instantes.")
    except (OSError, ValueError):
        raise HTTPException(502, "Não consegui consultar o IBGE agora. Tente de novo em instantes.")
    if isinstance(dados, list):
        dados = dados[0] if dados else {}
    nome = dados.get("nome") if isinstance(dados, dict) else None
    if not nome:
        raise HTTPException(404, "Esse código não existe no IBGE.")
    return nome


def poligono(codigo: str) -> dict:
    """Contorno oficial do município, como MultiPolygon em GeoJSON."""
    dados, ultimo = None, None
    for sufixo in VARIANTES_MALHA:
        try:
            dados = _pedir(f"{_base()}/v3/malhas/municipios/{codigo}{sufixo}")
            break
        except urllib.error.HTTPError as erro:
            ultimo = erro
            if erro.code == 404:
                raise HTTPException(404, "O IBGE não tem contorno para esse código.")
        except (OSError, ValueError) as erro:
            ultimo = erro
    if dados is None:
        raise HTTPException(502, "Não consegui baixar o contorno do IBGE agora. Tente de novo em instantes.")

    tipo = dados.get("type") if isinstance(dados, dict) else None
    if tipo == "FeatureCollection":
        geometrias = [f["geometry"] for f in dados.get("features", []) if f.get("geometry")]
    elif tipo == "Feature":
        geometrias = [dados["geometry"]]
    elif tipo in ("Polygon", "MultiPolygon"):
        geometrias = [dados]
    else:
        raise HTTPException(502, "O IBGE devolveu um formato inesperado.")
    poligonos = []
    for g in geometrias:
        if g["type"] == "Polygon":
            poligonos.append(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            poligonos.extend(g["coordinates"])
    if not poligonos:
        raise HTTPException(502, "O IBGE não devolveu nenhum polígono para esse código.")
    return {"type": "MultiPolygon", "coordinates": poligonos}
