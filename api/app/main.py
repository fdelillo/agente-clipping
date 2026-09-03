"""API de dominio del proyecto de social listening (Fase 1, Etapa 1).

La Etapa 0 dejó el andamiaje: la app arranca, se conecta a Postgres y
expone /health. Esta etapa suma el primer negocio real: los adapters de
fuentes (mock_x, mock_instagram) detrás de /sources, que capturan y
normalizan menciones al esquema común `Mention` (ver app/models.py y
app/sources/). El análisis con LLM (/analyze) y el informe llegan recién en
las Etapas 2 y 4.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from app.db import check_db, pool
from app.routers import sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Abrimos el pool acá (no al importar el módulo) para que la conexión a
    # Postgres se intente cuando la app ya está lista para servir, y lo
    # cerramos al apagar para no dejar conexiones colgadas.
    await pool.open()
    yield
    await pool.close()


app = FastAPI(title="social-listening-api", lifespan=lifespan)
app.include_router(sources.router)


@app.get("/")
async def root() -> dict:
    return {"service": "social-listening-api", "etapa": 1}


@app.get("/health")
async def health() -> Response:
    db_ok = await check_db()
    if db_ok:
        return JSONResponse({"status": "ok", "db": "ok"}, status_code=200)
    # 503 (Service Unavailable) y no 200: un healthcheck de Docker o un
    # monitor externo debe poder confiar en el código de estado, no solo
    # en el contenido del body.
    return JSONResponse({"status": "degraded", "db": "error"}, status_code=503)
