import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageOps, UnidentifiedImageError

# Desligamos o aviso padrão do Pillow e fazemos nossa própria checagem de tamanho
Image.MAX_IMAGE_PIXELS = None

MAX_BYTES = 8 * 1024 * 1024  # 8 MB por foto
MAX_PIXELS = 40_000_000      # 40 megapixels (proteção contra "bomba de imagem")
LADO_MAX = 1920              # a foto guardada tem no máximo 1920 px no lado maior
FORMATOS_ACEITOS = {"JPEG", "PNG", "WEBP"}

# Horário de Brasília (sem horário de verão desde 2019). Usado quando a foto
# traz a hora sem informar o fuso.
FUSO_BRASIL = timezone(timedelta(hours=-3))


class ImagemInvalida(ValueError):
    pass


@dataclass
class ImagemProcessada:
    jpeg: bytes
    largura: int
    altura: int
    hash_perceptual: int | None            # "impressão digital" visual da foto (64 bits)
    capturada_em: datetime | None          # data/hora gravada pela câmera (EXIF), se houver
    gps: tuple[float, float] | None        # (latitude, longitude) gravados pela câmera, se houver


def _fuso(texto: str) -> timezone:
    """'-03:00' -> fuso de -3 horas."""
    sinal = -1 if texto.startswith("-") else 1
    horas, minutos = texto.lstrip("+-").split(":")
    return timezone(sinal * timedelta(hours=int(horas), minutes=int(minutos)))


def _graus(valor, ref) -> float:
    d, m, s = (float(x) for x in valor)
    graus = d + m / 60 + s / 3600
    return -graus if str(ref) in ("S", "W") else graus


def _ler_exif(img: Image.Image):
    """Lê data e GPS gravados pela câmera. Qualquer problema vira None (EXIF é opcional)."""
    capturada_em = None
    gps = None
    try:
        exif = img.getexif()
        ifd = exif.get_ifd(0x8769)
        bruto = ifd.get(0x9003) or exif.get(0x0132)  # DateTimeOriginal ou DateTime
        if bruto:
            momento = datetime.strptime(str(bruto).strip(), "%Y:%m:%d %H:%M:%S")
            fuso = FUSO_BRASIL
            deslocamento = ifd.get(0x9011)  # OffsetTimeOriginal
            if deslocamento:
                try:
                    fuso = _fuso(str(deslocamento).strip())
                except (ValueError, TypeError):
                    pass
            capturada_em = momento.replace(tzinfo=fuso)
    except Exception:
        capturada_em = None
    try:
        g = img.getexif().get_ifd(0x8825)
        if 2 in g and 4 in g:
            lat = _graus(g[2], g.get(1, "N"))
            lon = _graus(g[4], g.get(3, "E"))
            if -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0):
                gps = (lat, lon)
    except Exception:
        gps = None
    return capturada_em, gps


def _hash_perceptual(img: Image.Image) -> int | None:
    """dHash de 64 bits: encolhe a foto para 9x8 cinza e compara pixels vizinhos.
    Fotos parecidas (redimensionadas, regravadas, com print de tela) dão hashes
    quase iguais. Foto lisa demais não tem "assinatura" confiável: devolve None."""
    pequena = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for linha in range(8):
        for col in range(8):
            esquerda = pequena[linha * 9 + col]
            direita = pequena[linha * 9 + col + 1]
            bits = (bits << 1) | (1 if esquerda > direita else 0)
    marcados = bin(bits).count("1")
    if marcados < 8 or marcados > 56:
        return None
    if bits >= 1 << 63:  # o banco guarda bigint com sinal
        bits -= 1 << 64
    return bits


def processar(dados: bytes) -> ImagemProcessada:
    """Valida a imagem de verdade (não confia no nome nem no content-type),
    lê data/GPS da câmera, corrige a rotação do celular, reduz o tamanho e
    regrava como JPEG.

    Regravar descarta os metadados (EXIF): some a localização GPS da casa
    de quem tirou a foto, o modelo do aparelho etc.
    """
    try:
        img = Image.open(io.BytesIO(dados))
        if img.format not in FORMATOS_ACEITOS:
            raise ImagemInvalida("formato não aceito")
        if img.width * img.height > MAX_PIXELS:
            raise ImagemInvalida("imagem grande demais")
        img.load()
    except ImagemInvalida:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImagemInvalida("arquivo não é uma imagem válida")

    capturada_em, gps = _ler_exif(img)  # antes de regravar (depois o EXIF some)

    img = ImageOps.exif_transpose(img)  # endireita fotos tiradas em pé/deitado
    img = img.convert("RGB")
    img.thumbnail((LADO_MAX, LADO_MAX))

    saida = io.BytesIO()
    img.save(saida, "JPEG", quality=85, optimize=True)
    return ImagemProcessada(
        jpeg=saida.getvalue(),
        largura=img.width,
        altura=img.height,
        hash_perceptual=_hash_perceptual(img),
        capturada_em=capturada_em,
        gps=gps,
    )
