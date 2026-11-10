
import hashlib
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from psycopg.types.json import Jsonb
from ..servico_yolo import VERSAO_MODELO, analisar_imagem

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse

from .. import auditoria
from ..config import settings
from ..db import get_conn
from ..deps import exigir_gestao_da_area, usuario_atual
from ..imagens import MAX_BYTES, ImagemInvalida, processar
from ..schemas import FotoOut

router = APIRouter(tags=["Fotos"])

MAX_FOTOS_POR_OCORRENCIA = 5
IDADE_MAX_FOTO_GALERIA_DIAS = 7
IDADE_MAX_FOTO_MIN = 10
RAIO_GPS_FOTO_M = 150
LIMITE_PARECIDA = 4

IdBigint = Annotated[int, Path(ge=1, le=2**63 - 1)]


def _foto_out(linha: dict) -> dict:
    return {**linha, "url": f"/midias/{linha['id_midia']}/arquivo"}


def _distancia_m(conn, id_ocorrencia: int, lat: float, lon: float) -> float:
    return conn.execute(
        """
        SELECT ST_Distance(
                   localizacao,
                   ST_SetSRID(ST_MakePoint(%s::float8, %s::float8), 4326)::geography
               )::float8 AS d
        FROM ocorrencias WHERE id_ocorrencia = %s
        """,
        (lon, lat, id_ocorrencia),
    ).fetchone()["d"]


@router.post("/ocorrencias/{id_ocorrencia}/fotos", response_model=FotoOut, status_code=201)
def enviar_foto(
    id_ocorrencia: IdBigint,
    arquivo: Annotated[UploadFile, File(description="Foto JPEG, PNG ou WEBP (até 8 MB)")],
    fonte: Annotated[Literal["camera", "galeria"], Form(
        description="De onde veio a foto: câmera do app ou galeria")] = "camera",
    latitude: Annotated[float | None, Form(ge=-90, le=90,
              description="Latitude do aparelho no momento da foto (obrigatória para foto da câmera)")] = None,
    longitude: Annotated[float | None, Form(ge=-180, le=180,
                description="Longitude do aparelho no momento da foto (obrigatória para foto da câmera)")] = None,
    u=Depends(usuario_atual),
    conn=Depends(get_conn),
):
    """Anexa uma foto a uma ocorrência.

    Câmera do app: GPS do aparelho + data recente. Galeria: exige data e GPS gravados na
    própria foto (EXIF), dentro de 7 dias e perto do local, e nunca é confirmada só pela IA.
    Gestor e admin: em qualquer ocorrência da sua área, sem passar pela IA."""

    o = conn.execute(
        """
        SELECT id_usuario_criador, status, id_area, tipo,
               (now() - criado_em) > make_interval(mins => %s) AS fora_do_prazo
        FROM ocorrencias WHERE id_ocorrencia = %s
        """,
        (settings.janela_foto_min, id_ocorrencia),
    ).fetchone()

    if o is None:
        raise HTTPException(404, "Ocorrência não encontrada")

    eh_gestao = u["papel"] in ("gestor", "admin")

    if eh_gestao:
        exigir_gestao_da_area(u, o["id_area"])

    if not eh_gestao:
        if o["id_usuario_criador"] != u["id_usuario"] or o["status"] != "aberta":
            raise HTTPException(403, "Você só pode enviar fotos nas suas próprias ocorrências abertas")

        if o["fora_do_prazo"]:
            raise HTTPException(
                403,
                f"O prazo para enviar fotos ({settings.janela_foto_min} min depois de registrar) "
                "acabou. Registre uma nova ocorrência.",
            )

        if fonte == "camera":
            if latitude is None or longitude is None:
                raise HTTPException(422, "Envie a latitude e a longitude do aparelho (tire a foto no local).")

            d = _distancia_m(conn, id_ocorrencia, latitude, longitude)

            if d > settings.raio_foto_m:
                raise HTTPException(
                    422,
                    f"Você parece estar a {round(d)} m do local da ocorrência. Tire a foto no local."
                )

    qtd = conn.execute(
        "SELECT count(*) AS n FROM ocorrencia_midias WHERE id_ocorrencia = %s",
        (id_ocorrencia,),
    ).fetchone()["n"]

    if qtd >= MAX_FOTOS_POR_OCORRENCIA:
        raise HTTPException(409, f"Limite de {MAX_FOTOS_POR_OCORRENCIA} fotos por ocorrência")

    dados = arquivo.file.read(MAX_BYTES + 1)

    if not dados:
        raise HTTPException(422, "Arquivo vazio")

    if len(dados) > MAX_BYTES:
        raise HTTPException(413, "Foto grande demais (máximo 8 MB)")

    hash_original = hashlib.sha256(dados).hexdigest()

    repetida = conn.execute(
        """
        SELECT om.id_ocorrencia
        FROM midias m
        JOIN ocorrencia_midias om ON om.id_midia = m.id_midia
        WHERE m.hash_arquivo = %s
        LIMIT 1
        """,
        (hash_original,),
    ).fetchone()

    if repetida:
        if repetida["id_ocorrencia"] == id_ocorrencia:
            raise HTTPException(409, "Esta foto já foi enviada nesta ocorrência")

        raise HTTPException(409, "Esta foto já foi usada em outra ocorrência. Tire uma foto nova.")

    try:
        img = processar(dados)
    except ImagemInvalida:
        raise HTTPException(415, "Arquivo inválido. Envie uma imagem JPEG, PNG ou WEBP.")

    analise = None

    if not eh_gestao:
        agora = datetime.now(timezone.utc)

        if fonte == "galeria":
            # Na galeria, a foto precisa carregar a própria prova: data e GPS gravados nela
            if img.capturada_em is None or img.gps is None:
                raise HTTPException(
                    422,
                    "Esta foto não tem data e localização gravadas. Ative a localização na "
                    "câmera do celular ou use a câmera do app.",
                )

            if not (
                agora - timedelta(days=IDADE_MAX_FOTO_GALERIA_DIAS)
                <= img.capturada_em
                <= agora + timedelta(minutes=5)
            ):
                raise HTTPException(
                    422, f"Esta foto foi tirada há mais de {IDADE_MAX_FOTO_GALERIA_DIAS} dias."
                )

        else:
            if img.capturada_em is not None and not (
                agora - timedelta(minutes=IDADE_MAX_FOTO_MIN)
                <= img.capturada_em
                <= agora + timedelta(minutes=5)
            ):
                raise HTTPException(422, "A data gravada na foto não é de agora. Tire a foto no momento.")

        if img.gps is not None:
            d = _distancia_m(conn, id_ocorrencia, *img.gps)

            if d > RAIO_GPS_FOTO_M:
                raise HTTPException(422, f"O local gravado na foto está a {round(d)} m da ocorrência.")

        if img.hash_perceptual is not None:
            parecida = conn.execute(
                """
                SELECT om.id_ocorrencia FROM midias m
                JOIN ocorrencia_midias om ON om.id_midia = m.id_midia
                WHERE om.id_ocorrencia <> %s
                  AND m.hash_perceptual IS NOT NULL
                  AND bit_count((m.hash_perceptual # %s::bigint)::bit(64)) <= %s
                LIMIT 1
                """,
                (id_ocorrencia, img.hash_perceptual, LIMITE_PARECIDA),
            ).fetchone()

            if parecida:
                raise HTTPException(409, "Esta foto é muito parecida com outra já enviada. Tire uma foto nova.")

        # IA: verifica se o tipo de ocorrência utiliza inteligência artificial
        usa_ia = conn.execute(
            "SELECT usa_ia FROM tipos_ocorrencia WHERE codigo = %s",
            (o["tipo"],)
        ).fetchone()["usa_ia"]

        if usa_ia:
            analise = analisar_imagem(img.jpeg)

            if analise["veredito"] == "recusada":
                raise HTTPException(
                    422,
                    "Não identificamos um buraco nesta foto. Chegue mais perto, "
                    "enquadre o buraco inteiro e tente de novo.",
                )

    relativo = f"ocorrencias/{id_ocorrencia}/{uuid.uuid4().hex}.jpg"
    destino = settings.uploads_dir / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(img.jpeg)

    origem = "foto_gestao" if eh_gestao else "foto_cidadao"
    finalidade = "revisao" if eh_gestao else "evidencia"
    nome = os.path.basename((arquivo.filename or "foto").replace("\\", "/"))[:255]
    lat_exif, lon_exif = img.gps if img.gps is not None else (None, None)

    try:
        m = conn.execute(
            """
            INSERT INTO midias
                (caminho_arquivo, nome_arquivo, tipo_mime, origem, hash_arquivo, hash_perceptual,
                 largura_pixels, altura_pixels, capturada_em, id_usuario_envio,
                 fonte_captura, exif_latitude, exif_longitude)
            VALUES (%s, %s, 'image/jpeg', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id_midia, origem, largura_pixels, altura_pixels, enviada_em
            """,
            (
                relativo, nome, origem, hash_original, img.hash_perceptual,
                img.largura, img.altura, img.capturada_em, u["id_usuario"],
                fonte, lat_exif, lon_exif
            ),
        ).fetchone()

        conn.execute(
            "INSERT INTO ocorrencia_midias (id_ocorrencia, id_midia, finalidade) VALUES (%s, %s, %s)",
            (id_ocorrencia, m["id_midia"], finalidade),
        )

        if analise is not None:
            for c in analise["caixas"]:
                conn.execute(
                    """
                    INSERT INTO deteccoes_ia
                        (id_midia, id_ocorrencia, classe_detectada, confianca,
                         bbox_x, bbox_y, bbox_largura, bbox_altura,
                         gravidade_estimada, metodo_estimativa, caracteristicas,
                         versao_modelo, processada_em)
                    VALUES (%s, %s, 'buraco', %s, %s, %s, %s, %s, %s, 'area_bbox', %s, %s, now())
                    """,
                    (
                        m["id_midia"], id_ocorrencia, c["confianca"],
                        c["x"], c["y"], c["largura"], c["altura"],
                        c["gravidade"], Jsonb({"area_relativa": c["area_relativa"]}),
                        VERSAO_MODELO
                    ),
                )

            # Só a câmera do app pode ser confirmada pela IA; galeria vai sempre para triagem
            confirmada = analise["veredito"] == "confirmada" and fonte == "camera"

            conn.execute(
                """
                UPDATE ocorrencias
                SET situacao_ia = CASE WHEN %s THEN 'confirmada'
                                       ELSE COALESCE(situacao_ia, 'triagem') END
                WHERE id_ocorrencia = %s
                """,
                (confirmada, id_ocorrencia),
            )

        auditoria.registrar(
            conn, "foto_enviada", u["id_usuario"], "midias", m["id_midia"],
            {
                "id_ocorrencia": id_ocorrencia,
                "fonte": fonte,
                "veredito_ia": analise["veredito"] if analise else None
            },
        )

    except Exception:
        destino.unlink(missing_ok=True)
        raise

    return _foto_out({**m, "finalidade": finalidade})


@router.get("/ocorrencias/{id_ocorrencia}/fotos", response_model=list[FotoOut])
def listar_fotos(id_ocorrencia: IdBigint, conn=Depends(get_conn)):
    existe = conn.execute(
        "SELECT 1 FROM ocorrencias WHERE id_ocorrencia = %s",
        (id_ocorrencia,),
    ).fetchone()

    if not existe:
        raise HTTPException(404, "Ocorrência não encontrada")

    linhas = conn.execute(
        """
        SELECT m.id_midia, m.origem, om.finalidade,
               m.largura_pixels, m.altura_pixels, m.enviada_em
        FROM ocorrencia_midias om
        JOIN midias m ON m.id_midia = om.id_midia
        WHERE om.id_ocorrencia = %s
        ORDER BY m.enviada_em, m.id_midia
        """,
        (id_ocorrencia,),
    ).fetchall()

    return [_foto_out(l) for l in linhas]


@router.get("/midias/{id_midia}/arquivo")
def baixar_foto(id_midia: IdBigint, conn=Depends(get_conn)):
    """Devolve a imagem. O caminho vem sempre do banco, nunca do usuário."""
    m = conn.execute(
        "SELECT caminho_arquivo, tipo_mime FROM midias WHERE id_midia = %s",
        (id_midia,),
    ).fetchone()

    if m is None:
        raise HTTPException(404, "Foto não encontrada")

    base = settings.uploads_dir.resolve()
    caminho = (base / m["caminho_arquivo"]).resolve()

    if not caminho.is_relative_to(base) or not caminho.is_file():
        raise HTTPException(404, "Arquivo da foto não encontrado")

    return FileResponse(
        caminho,
        media_type=m["tipo_mime"],
        headers={"Cache-Control": "public, max-age=86400"},
    )
