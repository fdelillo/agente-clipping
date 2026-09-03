"""Tests del router de /sources: GET /sources y GET /sources/{provider}/search.

Mismo patrón que test_health.py: httpx.ASGITransport en memoria, sin
servidor real ni DB (esta etapa no toca Postgres).
"""

import httpx

from app.main import app


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_list_sources_lista_ambos_providers():
    async with await _client() as client:
        response = await client.get("/sources")

    assert response.status_code == 200
    assert set(response.json()) == {"mock_x", "mock_instagram"}


async def test_search_devuelve_search_response_bien_formado():
    async with await _client() as client:
        response = await client.get("/sources/mock_x/search", params={"tag": "milei", "limit": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock_x"
    assert body["tag"] == "milei"
    assert body["count"] == 3
    assert len(body["mentions"]) == 3


async def test_search_instagram_tambien_funciona():
    async with await _client() as client:
        response = await client.get(
            "/sources/mock_instagram/search", params={"tag": "nike", "limit": 2}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock_instagram"
    assert body["count"] == 2


async def test_search_provider_desconocido_da_404():
    async with await _client() as client:
        response = await client.get("/sources/no_existe/search", params={"tag": "x"})

    assert response.status_code == 404
    assert "mock_x" in response.json()["detail"]


async def test_search_limit_cero_da_422():
    async with await _client() as client:
        response = await client.get("/sources/mock_x/search", params={"tag": "x", "limit": 0})

    assert response.status_code == 422


async def test_search_limit_excede_maximo_da_422():
    async with await _client() as client:
        response = await client.get("/sources/mock_x/search", params={"tag": "x", "limit": 101})

    assert response.status_code == 422


async def test_search_sin_tag_da_422():
    async with await _client() as client:
        response = await client.get("/sources/mock_x/search")

    assert response.status_code == 422
