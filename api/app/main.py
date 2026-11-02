from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .db import get_conn, pool, pool_admin
from .routers import admin, areas, auth, cep, fotos, gestao, ocorrencias, sinalizacoes


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=True, timeout=10)  # falha logo se não conseguir conectar
    if pool_admin is not None:
        pool_admin.open(wait=False)  # se a senha estiver errada, só as rotas /admin reclamam
    yield
    pool.close()
    if pool_admin is not None:
        pool_admin.close()


app = FastAPI(title="PavimentAI API", version="0.8.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(areas.router)
app.include_router(cep.router)
app.include_router(ocorrencias.router)
app.include_router(fotos.router)
app.include_router(gestao.router)
app.include_router(admin.router)
app.include_router(sinalizacoes.router)


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
