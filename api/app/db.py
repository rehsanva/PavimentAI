from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
