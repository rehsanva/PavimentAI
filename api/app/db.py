from fastapi import HTTPException
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import settings

CONNINFO = make_conninfo(
    host=settings.db_host,
    port=settings.db_port,
    dbname=settings.db_name,
    user=settings.db_user,
    password=settings.db_password,
)

# Pool de conexões: a API reaproveita conexões em vez de abrir uma por requisição.
# Cada linha vem como dicionário (ex.: row["id_ocorrencia"]).
pool = ConnectionPool(
    conninfo=CONNINFO,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=False,  # aberto no início da API (veja main.py)
)


def get_conn():
    """Dependência do FastAPI: uma conexão = uma transação por requisição.

    Se a rota terminar sem erro, o banco faz COMMIT automaticamente.
    Se der exceção, faz ROLLBACK (nada fica pela metade).
    """
    with pool.connection() as conn:
        yield conn


# ----------------------------------------------------------------------------
# Segunda conexão, só para o painel de admin. Usa OUTRO usuário do banco
# (pavimentai_admin), o único com permissão de criar cidades e mudar papéis.
# Assim, uma falha numa rota pública nunca consegue promover alguém a admin.
pool_admin = None
if settings.db_admin_user and settings.db_admin_password:
    pool_admin = ConnectionPool(
        conninfo=make_conninfo(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_admin_user,
            password=settings.db_admin_password,
        ),
        min_size=0,
        max_size=3,
        kwargs={"row_factory": dict_row},
        open=False,
    )


def get_conn_admin():
    """Como get_conn, mas com o usuário de admin do banco. Só as rotas /admin usam."""
    if pool_admin is None:
        raise HTTPException(
            503, "A conexão de administração não está configurada "
                 "(veja DB_ADMIN_USER e DB_ADMIN_PASSWORD no .env).")
    try:
        with pool_admin.connection(timeout=5) as conn:
            yield conn
    except PoolTimeout:
        raise HTTPException(
            503, "Não consegui conectar com o usuário de administração do banco. "
                 "Confira DB_ADMIN_USER e DB_ADMIN_PASSWORD no .env.")
