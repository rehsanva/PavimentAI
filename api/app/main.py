from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .db import get_conn, pool
from .routers import auth, fotos, ocorrencias


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=True, timeout=10)  # falha logo se não conseguir conectar
    yield
    pool.close()


app = FastAPI(title="PavimentAI API", version="0.4.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(ocorrencias.router)
app.include_router(fotos.router)


@app.get("/saude")
def saude(conn=Depends(get_conn)):
    """Teste de ponta a ponta: API -> banco -> PostGIS -> view do mapa."""
    row = conn.execute(
        """
        SELECT current_user        AS usuario_banco,
               postgis_version()   AS postgis,
               (SELECT count(*) FROM vw_mapa_ocorrencias) AS ocorrencias_abertas
        """
    ).fetchone()
    return {"status": "ok", **row}
