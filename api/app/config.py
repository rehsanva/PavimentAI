from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Lê as variáveis do arquivo .env (na pasta onde você roda o uvicorn)
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "pavimentai"
    db_user: str = "pavimentai_app"
    db_password: str  # obrigatória: sem ela a API nem sobe

    jwt_secret: str = Field(min_length=32)  # obrigatória, mínimo 32 caracteres
    jwt_expira_minutos: int = 60
    ambiente: str = "dev"  # "dev" ou "prod"

    raio_duplicidade_m: int = 15  # ocorrência aberta a menos de X metros = possível duplicada
    limite_ocorrencias_hora: int = 20  # máximo de registros por usuário por hora

    # Antifraude das fotos de cidadãos
    janela_foto_min: int = 15  # a foto só vale até X minutos depois de registrar a ocorrência
    raio_foto_m: int = 100     # o aparelho precisa estar a menos de X metros da ocorrência

    # Pasta onde as fotos ficam guardadas (por padrão: api/uploads).
    # Na hospedagem, aponte para um disco/volume persistente com UPLOADS_DIR no .env.
    uploads_dir: Path = Path(__file__).resolve().parents[1] / "uploads"

    pasta_uploads: str = "uploads"  # onde as fotos ficam salvas (relativa à pasta api)
    max_foto_mb: int = 8  # tamanho máximo de cada foto enviada
    max_fotos_por_ocorrencia: int = 5
    limite_fotos_hora: int = 40  # máximo de fotos por usuário por hora


settings = Settings()
