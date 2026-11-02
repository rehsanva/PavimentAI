"""Baixa o contorno oficial de um município (IBGE) e gera um arquivo .sql.

Uso (dentro da pasta api, com a venv ativa):
    python scripts/baixar_limite.py 3529401 Mauá
    python scripts/baixar_limite.py 3543303            (o nome vem do IBGE)

Cria sql/limite_<nome>.sql. Depois é só aplicar com aplicar_sql.py.
Se o código não for do município que você digitou, o script avisa e para.
Não precisa instalar nada além do que o projeto já tem.
"""
import gzip
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.getenv("IBGE_BASE", "https://servicodados.ibge.gov.br/api")
URL_MALHA = BASE + "/v3/malhas/municipios/{codigo}"
URL_NOME = BASE + "/v1/localidades/municipios/{codigo}"
# Tenta a melhor qualidade primeiro; se a API recusar, tenta as outras formas
VARIANTES = [
    "?formato=application/vnd.geo+json&qualidade=maxima",
    "?formato=application/vnd.geo+json&qualidade=4",
    "?formato=application/vnd.geo+json",
]


def _pedir(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "PavimentAI-script"})
    with urllib.request.urlopen(req, timeout=60) as resposta:
        corpo = resposta.read()
        # O IBGE às vezes responde compactado (gzip): descompacta antes de ler
        if resposta.headers.get("Content-Encoding", "").lower() == "gzip" or corpo[:2] == b"\x1f\x8b":
            corpo = gzip.decompress(corpo)
    return json.loads(corpo.decode("utf-8"))


def baixar(codigo: str) -> dict:
    ultimo_erro = None
    for sufixo in VARIANTES:
        try:
            return _pedir(URL_MALHA.format(codigo=codigo) + sufixo)
        except (OSError, ValueError) as erro:  # inclui falha de rede, gzip ruim e JSON inválido
            ultimo_erro = erro
    raise SystemExit(f"Não consegui baixar do IBGE: {ultimo_erro}\nConfira a internet e o código do município.")


def nome_oficial(codigo: str) -> str | None:
    """Nome que o IBGE usa para esse código (para conferir se você digitou o código certo)."""
    try:
        dados = _pedir(URL_NOME.format(codigo=codigo))
        if isinstance(dados, list):
            dados = dados[0] if dados else {}
        return dados.get("nome")
    except (OSError, ValueError, AttributeError):
        return None


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def igual(a: str, b: str) -> bool:
    limpar = lambda t: re.sub(r"[^a-z0-9]+", " ", sem_acento(t).lower()).strip()
    return limpar(a) == limpar(b)


def extrair_geometria(dados: dict) -> dict:
    """Junta tudo num MultiPolygon, seja qual for o formato que o IBGE devolver."""
    tipo = dados.get("type")
    if tipo == "FeatureCollection":
        geometrias = [f["geometry"] for f in dados.get("features", []) if f.get("geometry")]
    elif tipo == "Feature":
        geometrias = [dados["geometry"]]
    elif tipo in ("Polygon", "MultiPolygon"):
        geometrias = [dados]
    else:
        raise SystemExit(f"Formato inesperado do IBGE (type={tipo!r}).")

    poligonos = []
    for g in geometrias:
        if g["type"] == "Polygon":
            poligonos.append(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            poligonos.extend(g["coordinates"])
    if not poligonos:
        raise SystemExit("O IBGE não devolveu nenhum polígono para esse código.")
    return {"type": "MultiPolygon", "coordinates": poligonos}


def gerar_sql(geometria: dict, nome: str, codigo: str, tolerancia_m: int = 30) -> str:
    geojson = json.dumps(geometria, separators=(",", ":"))
    nome_sql = nome.replace("'", "''")
    return f"""-- Limite oficial do município de {nome} (código IBGE {codigo}).
-- Gerado por scripts/baixar_limite.py. Pode ser aplicado mais de uma vez.
INSERT INTO public.areas_atendimento (nome, codigo_ibge, geometria)
VALUES (
    '{nome_sql}',
    '{codigo}',
    ST_SetSRID(
        ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_GeomFromGeoJSON('{geojson}')), 3)),
        4326
    )::geography
)
ON CONFLICT (codigo_ibge) DO UPDATE
    SET nome = EXCLUDED.nome, geometria = EXCLUDED.geometria, ativa = true;

-- Liga à área as ocorrências que já existiam dentro dela e ainda não tinham cidade
UPDATE public.ocorrencias o
SET id_area = a.id_area
FROM public.areas_atendimento a
WHERE a.codigo_ibge = '{codigo}'
  AND o.id_area IS NULL
  AND ST_DWithin(a.geometria, o.localizacao, {tolerancia_m});

-- Liga a esta área os cidadãos que já tinham informado morar nesta cidade
UPDATE public.usuarios u
SET id_area_residencia = a.id_area
FROM public.areas_atendimento a
WHERE a.codigo_ibge = '{codigo}'
  AND u.codigo_ibge_residencia = a.codigo_ibge
  AND u.id_area_residencia IS NULL;
"""


def nome_de_arquivo(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", sem_acento(nome).lower()).strip("_") or "municipio"


def main() -> None:
    args = sys.argv[1:]
    if not 1 <= len(args) <= 2 or not re.fullmatch(r"\d{7}", args[0]):
        raise SystemExit("Uso: python scripts/baixar_limite.py CODIGO_IBGE_7_DIGITOS [\"Nome do município\"]\n"
                         "Exemplo: python scripts/baixar_limite.py 3529401 Mauá")
    codigo = args[0]
    informado = args[1] if len(args) == 2 else None

    oficial = nome_oficial(codigo)
    if oficial and informado and not igual(oficial, informado):
        raise SystemExit(f"Atenção: o código {codigo} é do município \"{oficial}\", e não de \"{informado}\".\n"
                         "Confira o código (ou rode sem o nome para usar o do IBGE). Nada foi criado.")
    nome = oficial or informado
    if not nome:
        raise SystemExit("Não consegui descobrir o nome desse código no IBGE. Rode de novo informando o nome.")
    if not oficial:
        print("(Não consegui conferir o nome no IBGE; confira se o código está certo.)")

    print(f"Baixando o limite de {nome} ({codigo}) no IBGE...")
    geometria = extrair_geometria(baixar(codigo))
    pontos = sum(len(anel) for poligono in geometria["coordinates"] for anel in poligono)

    destino = Path(__file__).resolve().parents[1] / "sql" / f"limite_{nome_de_arquivo(nome)}.sql"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(gerar_sql(geometria, nome, codigo), encoding="utf-8")
    print(f"Pronto! {len(geometria['coordinates'])} polígono(s), {pontos} pontos.")
    print(f"Arquivo criado: {destino}")
    print("Agora aplique com:  python scripts/aplicar_sql.py " + f"sql/{destino.name}")


if __name__ == "__main__":
    main()
