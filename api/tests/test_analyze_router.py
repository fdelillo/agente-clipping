"""Tests de POST /analyze. Mismo patrón que test_sources_router.py:
httpx.ASGITransport en memoria, sin servidor real. El servicio de LLM se
parchea (AsyncMock) para no depender de Groq ni de app/llm/client.py, que
ya tiene su propia batería de tests.
"""

from unittest.mock import AsyncMock, patch

import httpx

from app.llm.client import LLMError
from app.llm.models import Analysis
from app.main import app


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_analyze_devuelve_200_con_estructura_esperada():
    fake_results = [
        Analysis(
            external_id="1",
            analyzed=True,
            sentiment="positive",
            sentiment_score=0.5,
            topics=["general"],
            llm_rationale="r",
            analyzed_at="2026-01-01T00:00:00+00:00",
        ),
        Analysis(external_id="2", analyzed=False, error="algo falló"),
    ]
    body = {
        "items": [
            {"external_id": "1", "copy_text": "buenísimo"},
            {"external_id": "2", "copy_text": "una porquería"},
        ]
    }
    with patch("app.routers.analyze.analyze_items", new=AsyncMock(return_value=fake_results)):
        async with await _client() as client:
            response = await client.post("/analyze", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["analyzed_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["results"][0]["external_id"] == "1"
    assert payload["results"][0]["sentiment"] == "positive"
    assert payload["results"][1]["analyzed"] is False


async def test_analyze_items_vacio_da_422():
    async with await _client() as client:
        response = await client.post("/analyze", json={"items": []})

    assert response.status_code == 422


async def test_analyze_sin_items_da_422():
    async with await _client() as client:
        response = await client.post("/analyze", json={})

    assert response.status_code == 422


async def test_analyze_key_ausente_da_503():
    with patch(
        "app.routers.analyze.analyze_items",
        new=AsyncMock(side_effect=LLMError("GROQ_API_KEY no está configurada.")),
    ):
        async with await _client() as client:
            response = await client.post(
                "/analyze", json={"items": [{"external_id": "1", "copy_text": "x"}]}
            )

    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]
