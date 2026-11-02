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

    # Cerca geográfica: tolerância (erro do GPS perto da divisa do município)
    tolerancia_area_m: int = 30

    # Conexão separada, só do painel de admin (cadastrar cidades e mudar papéis).
    # Criada com: python scripts/criar_papel_admin_db.py  (veja as instruções)
    db_admin_user: str | None = None
    db_admin_password: str | None = None
    ibge_api_url: str = "https://servicodados.ibge.gov.br/api"

    # Consulta de CEP (ViaCEP). Dá para trocar por outro serviço pelo .env (CEP_API_URL)
    cep_api_url: str = "https://viacep.com.br/ws"
    cep_timeout_s: int = 5
    dias_troca_residencia: int = 30  # o cidadão só pode trocar a cidade de residência a cada X dias

    # Antifraude das fotos de cidadãos
    janela_foto_min: int = 15  # a foto só vale até X minutos depois de registrar a ocorrência
    raio_foto_m: int = 100     # o aparelho precisa estar a menos de X metros da ocorrência

    # Pasta onde as fotos ficam guardadas (por padrão: api/uploads).
    # Na hospedagem, aponte para um disco/volume persistente com UPLOADS_DIR no .env.
    uploads_dir: Path = Path(__file__).resolve().parents[1] / "uploads"


settings = Settings()
