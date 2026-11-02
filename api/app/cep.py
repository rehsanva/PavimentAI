import json
import re
import urllib.error
import urllib.request
from functools import lru_cache

from fastapi import HTTPException

from .config import settings


@lru_cache(maxsize=512)
def _consultar(cep: str) -> dict:
    """Pergunta ao serviço de CEP (ViaCEP). Só respostas boas ficam guardadas na memória:
    erro nunca vira cache, então uma falha passageira não "gruda"."""
    url = f"{settings.cep_api_url.rstrip('/')}/{cep}/json/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PavimentAI/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=settings.cep_timeout_s) as resposta:
            dados = json.load(resposta)
    except urllib.error.HTTPError as erro:
        if erro.code in (400, 404):
            raise HTTPException(422, "CEP inválido ou não encontrado.")
        raise HTTPException(503, "Não consegui consultar o CEP agora. Tente de novo em instantes.")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise HTTPException(503, "Não consegui consultar o CEP agora. Tente de novo em instantes.")

    if not isinstance(dados, dict) or dados.get("erro") in (True, "true"):
        raise HTTPException(422, "CEP não encontrado.")
    ibge = str(dados.get("ibge") or "")
    if not re.fullmatch(r"\d{7}", ibge):
        raise HTTPException(422, "Não consegui identificar a cidade deste CEP.")
    return {
        "codigo_ibge": ibge,
        "municipio": dados.get("localidade"),
        "uf": dados.get("uf"),
        "logradouro": dados.get("logradouro") or None,  # só para o app mostrar; não é guardado
        "bairro": dados.get("bairro") or None,
    }


def consultar_cep(cep: str) -> dict:
    return dict(_consultar(cep))
