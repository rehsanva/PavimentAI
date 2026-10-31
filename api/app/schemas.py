import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

Tipo = Literal["buraco", "acessibilidade"]
CategoriaAcessibilidade = Literal[
    "calcada_danificada", "ausencia_rampa", "piso_tatil", "travessia", "obstaculo", "outro"
]
Gravidade = Literal["leve", "moderado", "grave"]


# ---------------------------------------------------------------- usuários
class CadastroIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    email: EmailStr
    telefone: str
    senha: str = Field(min_length=8, max_length=128)

    @field_validator("nome")
    @classmethod
    def limpar_nome(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("nome muito curto")
        return v

    @field_validator("telefone")
    @classmethod
    def so_digitos(cls, v: str) -> str:
        digitos = re.sub(r"\D", "", v)
        if not 10 <= len(digitos) <= 13:
            raise ValueError("telefone inválido (use DDD + número)")
        return digitos


class VerificarEmailIn(BaseModel):
    email: EmailStr
    codigo: str = Field(pattern=r"^\d{6}$")


class ReenviarIn(BaseModel):
    email: EmailStr


class UsuarioOut(BaseModel):
    id_usuario: int
    nome: str
    email: str
    telefone: str
    papel: str
    status_conta: str
    email_verificado: bool
    telefone_verificado: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# -------------------------------------------------------------- ocorrências
class OcorrenciaIn(BaseModel):
    tipo: Tipo
    categoria: CategoriaAcessibilidade | None = None  # só para acessibilidade
    descricao: str | None = Field(default=None, max_length=1000)
    gravidade: Gravidade | None = None  # só para buraco (opinião do cidadão)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # Se já existe uma ocorrência por perto, a API avisa (409).
    # Mande true para registrar mesmo assim.
    criar_mesmo_assim: bool = False

    @field_validator("descricao")
    @classmethod
    def limpar_descricao(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None

    @model_validator(mode="after")
    def regras_do_tipo(self):
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError("localização inválida (0, 0)")
        if self.tipo == "buraco" and self.categoria is not None:
            raise ValueError("buraco não tem categoria")
        if self.tipo == "acessibilidade":
            if self.categoria is None:
                raise ValueError("informe a categoria do problema de acessibilidade")
            if self.gravidade is not None:
                raise ValueError("gravidade só se aplica a buracos")
        return self


class OcorrenciaOut(BaseModel):
    id_ocorrencia: int
    tipo: str
    categoria: str | None
    descricao: str | None
    gravidade: str | None
    latitude: float
    longitude: float
    status: str
    canal_registro: str
    criado_em: datetime
    verificada_em: datetime | None
    id_ocorrencia_principal: int | None
