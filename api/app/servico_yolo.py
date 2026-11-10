from io import BytesIO
from pathlib import Path

from PIL import Image
from ultralytics import YOLO

LIMIAR_MINIMO = 0.25
LIMIAR_CONFIRMA = 0.50
VERSAO_MODELO = "yolo11n-dataset-v3"   # ajuste se o nome do seu modelo for outro

# PROVISÓRIO: gravidade pela área da caixa (fração da foto). Calibrar com fotos reais.
AREA_MODERADO = 0.02
AREA_GRAVE = 0.06

RAIZ = Path(__file__).resolve().parents[2]   # pasta pavimentAI
CAMINHO_MODELO = RAIZ / "ml" / "models" / "yolo11n" / "best.pt"

_modelo = None


def carregar_modelo():
    global _modelo
    if _modelo is None:
        _modelo = YOLO(str(CAMINHO_MODELO))
    return _modelo


def _entre_0_e_1(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _gravidade(area: float) -> str:
    if area >= AREA_GRAVE:
        return "grave"
    if area >= AREA_MODERADO:
        return "moderado"
    return "leve"


def analisar_imagem(dados_jpeg: bytes) -> dict:
    imagem = Image.open(BytesIO(dados_jpeg)).convert("RGB")
    r = carregar_modelo().predict(imagem, imgsz=640, conf=LIMIAR_MINIMO, verbose=False)[0]
    caixas = []
    for b in r.boxes:
        x1, y1, x2, y2 = (_entre_0_e_1(v) for v in b.xyxyn[0].tolist())
        area = (x2 - x1) * (y2 - y1)
        caixas.append({
            "confianca": _entre_0_e_1(b.conf[0].item()),
            "x": x1, "y": y1, "largura": x2 - x1, "altura": y2 - y1,
            "area_relativa": area,
            "gravidade": _gravidade(area),
        })
    melhor = max((c["confianca"] for c in caixas), default=0.0)
    if melhor >= LIMIAR_CONFIRMA:
        veredito = "confirmada"
    elif melhor >= LIMIAR_MINIMO:
        veredito = "triagem"
    else:
        veredito = "recusada"
    return {"veredito": veredito, "melhor_confianca": melhor, "caixas": caixas}


def analisar_foto(caminho: str) -> dict:
    """Versão para testes no terminal (usada pelo testar_modelo.py)."""
    return analisar_imagem(Path(caminho).read_bytes())