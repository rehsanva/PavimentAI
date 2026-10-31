from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from .db import get_conn
from .seguranca import ler_token

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


def usuario_atual(token: str = Depends(oauth2), conn=Depends(get_conn)):
    """Descobre quem está logado a partir do token.

    Confere no banco a cada requisição: se o gestor suspender uma conta,
    o bloqueio vale na hora, mesmo com o token ainda dentro do prazo.
    """
    erro = HTTPException(401, "Token inválido ou expirado",
                         headers={"WWW-Authenticate": "Bearer"})
    id_usuario = ler_token(token)
    if id_usuario is None:
        raise erro
    u = conn.execute(
        """
        SELECT id_usuario, nome, email, telefone, papel, status_conta,
               email_verificado, telefone_verificado
        FROM usuarios WHERE id_usuario = %s
        """,
        (id_usuario,),
    ).fetchone()
    if u is None or u["status_conta"] != "ativa":
        raise erro
    return u


def exigir_papel(*papeis: str):
    """Uso: Depends(exigir_papel('gestor', 'admin')) protege rotas de gestão."""
    def checar(u=Depends(usuario_atual)):
        if u["papel"] not in papeis:
            raise HTTPException(403, "Sem permissão para esta ação")
        return u
    return checar
