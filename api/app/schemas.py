import re

from fastapi import APIRouter
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

Tipo = Literal["buraco", "acessibilidade"]
CategoriaAcessibilidade = Literal[
    "calcada_danificada", "ausencia_rampa", "piso_tatil", "travessia", "obstaculo", "outro"
]
Gravidade = Literal["leve", "moderado", "grave"]
StatusOcorrencia = Literal["aberta", "resolvida", "descartada", "duplicada"]
MotivoSinalizacao = Literal[
    "duplicidade", "localizacao_incorreta", "informacao_incorreta", "nao_e_um_problema", "outro"
]


# ---------------------------------------------------------------- usuários
def _cep_so_digitos(v: str) -> str:
    digitos = re.sub(r"\D", "", v)
    if len(digitos) != 8:
        raise ValueError("CEP inválido (são 8 números)")
    return digitos


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


class ResidenciaIn(BaseModel):
    cep: str

    @field_validator("cep")
    @classmethod
    def validar_cep(cls, v: str) -> str:
        return _cep_so_digitos(v)

class AtualizarPerfilIn(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    telefone: str | None = None

    @field_validator("nome")
    @classmethod
    def limpar_nome(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("nome muito curto")
        return v

    @field_validator("telefone")
    @classmethod
    def so_digitos(cls, v: str | None) -> str | None:
        if v is None:
            return None
        digitos = re.sub(r"\D", "", v)
        if not 10 <= len(digitos) <= 13:
            raise ValueError("telefone inválido (use DDD + número)")
        return digitos

    @model_validator(mode="after")
    def pelo_menos_um(self):
        if self.nome is None and self.telefone is None:
            raise ValueError("informe o nome ou o telefone")
        return self


class TrocarSenhaIn(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=128)
    senha_nova: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def diferente(self):
        if self.senha_nova == self.senha_atual:
            raise ValueError("a senha nova precisa ser diferente da atual")
        return self


class ConfirmarSenhaIn(BaseModel):
    senha: str = Field(min_length=1, max_length=128)

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
    residencia_informada: bool = False
    municipio_residencia: str | None = None
    uf_residencia: str | None = None
    id_area_residencia: int | None = None  # cidade de residência, se ela já for atendida
    id_area_gestao: int | None = None      # só para gestor: cidade que ele administra


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# -------------------------------------------------------------- ocorrências
class OcorrenciaIn(BaseModel):
    tipo: str = Field(pattern=r"^[a-z][a-z0-9_]{1,19}$")
    categoria: str | None = Field(default=None, max_length=40)
    descricao: str | None = Field(default=None, max_length=1000)
    gravidade: Gravidade | None = None  # só para tipos que usam gravidade
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
    def local_valido(self):
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError("localização inválida (0, 0)")
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
    id_area: int | None = None  # cidade/área de atendimento onde foi registrada


# -------------------------------------------------------------------- fotos
class FotoOut(BaseModel):
    id_midia: int
    url: str  # caminho para baixar a imagem (ex.: /midias/7/arquivo)
    origem: str
    finalidade: str
    largura_pixels: int | None
    altura_pixels: int | None
    enviada_em: datetime


# ------------------------------------------------------------------ gestão
class MudarStatusIn(BaseModel):
    status: StatusOcorrencia
    justificativa: str | None = Field(default=None, max_length=1000)
    id_ocorrencia_principal: int | None = Field(default=None, ge=1)  # só para "duplicada"
    gravidade_verificada: Gravidade | None = None  # só para buraco: gravidade confirmada pelo gestor

    @field_validator("justificativa")
    @classmethod
    def limpar_justificativa(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def regras(self):
        if self.status == "descartada" and (not self.justificativa or len(self.justificativa) < 5):
            raise ValueError("explique o motivo do descarte (mínimo de 5 letras)")
        if self.status == "duplicada" and self.id_ocorrencia_principal is None:
            raise ValueError("informe qual é a ocorrência principal (id_ocorrencia_principal)")
        if self.status != "duplicada" and self.id_ocorrencia_principal is not None:
            raise ValueError("id_ocorrencia_principal só vale para o status duplicada")
        return self


class SinalizacaoIn(BaseModel):
    motivo: MotivoSinalizacao
    descricao: str | None = Field(default=None, max_length=500)
    id_ocorrencia_original: int | None = Field(default=None, ge=1)  # só para duplicidade

    @field_validator("descricao")
    @classmethod
    def limpar_descricao(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def regras(self):
        if self.motivo == "duplicidade" and self.id_ocorrencia_original is None:
            raise ValueError("informe qual é a ocorrência original (id_ocorrencia_original)")
        if self.motivo != "duplicidade" and self.id_ocorrencia_original is not None:
            raise ValueError("id_ocorrencia_original só vale para o motivo duplicidade")
        return self


class AnaliseIn(BaseModel):
    resultado: Literal["aceita", "rejeitada"]

class TriagemIn(BaseModel):
    decisao: Literal["aprovada", "recusada"]
    motivo: str | None = Field(default=None, max_length=1000)
    gravidade_verificada: Gravidade | None = None  # só ao aprovar

    @field_validator("motivo")
    @classmethod
    def limpar_motivo(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def regras(self):
        if self.decisao == "recusada":
            if not self.motivo or len(self.motivo) < 5:
                raise ValueError("explique o motivo da recusa (mínimo de 5 letras)")
            if self.gravidade_verificada is not None:
                raise ValueError("gravidade só vale ao aprovar")
        return self

# -------------------------------------------------------------------- admin
class AreaNovaIn(BaseModel):
    codigo_ibge: str = Field(pattern=r"^\d{7}$", description="Código IBGE do município (7 números)")
    exige_residencia: bool = False  # true = só moradores registram ocorrências nesta cidade


class AreaAlterarIn(BaseModel):
    ativa: bool | None = None
    exige_residencia: bool | None = None
    nome: str | None = Field(default=None, min_length=2, max_length=120)

    @model_validator(mode="after")
    def pelo_menos_um(self):
        if self.ativa is None and self.exige_residencia is None and self.nome is None:
            raise ValueError("informe pelo menos um campo para alterar")
        return self


class PapelIn(BaseModel):
    papel: Literal["cidadao", "gestor", "admin"]
    id_area_gestao: int | None = Field(default=None, ge=1)  # obrigatório só para gestor

    @model_validator(mode="after")
    def regras(self):
        if self.papel == "gestor" and self.id_area_gestao is None:
            raise ValueError("para gestor, informe o id_area_gestao (a cidade que ele administra)")
        if self.papel != "gestor" and self.id_area_gestao is not None:
            raise ValueError("id_area_gestao só vale para gestor")
        return self

# ------------------------------------------------------------ catálogo de tipos
_CAT = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def _checar_categorias(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    if len(set(v)) != len(v):
        raise ValueError("categorias repetidas")
    for c in v:
        if not _CAT.match(c):
            raise ValueError(f"categoria inválida: {c} (use minúsculas, números e _)")
    return v


class TipoNovoIn(BaseModel):
    codigo: str = Field(pattern=r"^[a-z][a-z0-9_]{1,19}$", description="Ex.: bueiro (minúsculas, até 20)")
    nome: str = Field(min_length=2, max_length=60)
    usa_gravidade: bool = False
    categorias: list[str] = Field(default_factory=list, max_length=30)
    ordem: int = Field(default=100, ge=0, le=10000)

    @field_validator("categorias")
    @classmethod
    def validar_categorias(cls, v):
        return _checar_categorias(v)


class TipoAlterarIn(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=60)
    ativo: bool | None = None
    ordem: int | None = Field(default=None, ge=0, le=10000)
    categorias: list[str] | None = Field(default=None, max_length=30)

    @field_validator("categorias")
    @classmethod
    def validar_categorias(cls, v):
        return _checar_categorias(v)

    @model_validator(mode="after")
    def pelo_menos_um(self):
        if all(x is None for x in (self.nome, self.ativo, self.ordem, self.categorias)):
            raise ValueError("informe pelo menos um campo para alterar")
        return self
    

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalizar_email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("e-mail inválido")
    return v


class EsqueciSenhaIn(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def email_valido(cls, v: str) -> str:
        return _normalizar_email(v)


class RedefinirSenhaIn(BaseModel):
    email: str = Field(max_length=254)
    codigo: str = Field(pattern=r"^\d{6}$", description="Código de 6 dígitos recebido por e-mail")
    senha_nova: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def email_valido(cls, v: str) -> str:
        return _normalizar_email(v)
    
    
