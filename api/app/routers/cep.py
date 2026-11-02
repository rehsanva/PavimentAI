from typing import Annotated

from fastapi import APIRouter, Depends, Path

from .. import residencia
from ..db import get_conn

router = APIRouter(prefix="/cep", tags=["CEP"])


@router.get("/{cep}")
def consultar(cep: Annotated[str, Path(pattern=r"^\d{5}-?\d{3}$")], conn=Depends(get_conn)):
    """Usado pela tela de cadastro: preenche cidade/bairro e avisa se a cidade já é atendida."""
    return residencia.resolver(conn, cep.replace("-", ""))
