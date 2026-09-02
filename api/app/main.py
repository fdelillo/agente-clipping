"""API de dominio del proyecto de social listening (Fase 1, Etapa 0).

En esta etapa la API todavía no hace nada de negocio: eso llega en las
Etapas 1 y 2 (adapters de fuentes, normalización, análisis con LLM). Acá
solo dejamos el andamiaje funcionando: la app arranca, se conecta a
Postgres y expone /health para que Docker y n8n puedan verificar que está
viva.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from app.db import check_db, pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Abrimos el pool acá (no al importar el módulo) para que la conexión a
    # Postgres se intente cuando la app ya está lista para servir, y lo
    # cerramos al apagar para no dejar conexiones colgadas.
    await pool.open()
    yield
    await pool.close()


app = FastAPI(title="social-listening-api", lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {"service": "social-listening-api", "etapa": 0}


@app.get("/health")
async def health() -> Response:
    db_ok = await check_db()
    if db_ok:
        return JSONResponse({"status": "ok", "db": "ok"}, status_code=200)
    # 503 (Service Unavailable) y no 200: un healthcheck de Docker o un
    # monitor externo debe poder confiar en el código de estado, no solo
    # en el contenido del body.
    return JSONResponse({"status": "degraded", "db": "error"}, status_code=503)
