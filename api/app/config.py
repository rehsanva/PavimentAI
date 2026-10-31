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


settings = Settings()
