"""Pool de conexiones a Postgres.

El pool se crea acá pero NO se abre a nivel de módulo: psycopg 3.2 deprecó
abrir el pool implícitamente en el constructor (podía arrancar a conectar
antes de que el event loop de asyncio esté corriendo). La apertura real
pasa en el lifespan de FastAPI (ver app/main.py), que es el lugar correcto
para inicializar y liberar recursos de vida larga.
"""

from psycopg_pool import AsyncConnectionPool

from app.config import settings

# open=False: el pool queda "armado" pero sin conectar todavía. Recién se
# conecta cuando el lifespan de la app llama a pool.open().
pool = AsyncConnectionPool(conninfo=settings.database_url, open=False)


async def check_db() -> bool:
    """Chequeo mínimo de salud: ¿la base responde SELECT 1?"""
    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        # Cualquier falla de conexión/consulta se traduce en "no está ok".
        # /health no necesita distinguir el motivo, solo el estado.
        return False
