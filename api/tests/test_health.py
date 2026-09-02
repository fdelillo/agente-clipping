"""Tests de /health, sin necesidad de una base de datos real.

Parcheamos app.db.check_db para simular ambos escenarios (DB arriba / DB
caída) y usamos httpx.ASGITransport para hablarle a la app FastAPI
directamente en memoria, sin levantar un servidor de verdad.
"""

from unittest.mock import AsyncMock, patch

import httpx

from app.main import app


async def test_health_ok():
    with patch("app.main.check_db", new=AsyncMock(return_value=True)):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


async def test_health_degraded():
    with patch("app.main.check_db", new=AsyncMock(return_value=False)):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
