"""Tests de app/llm/client.py: armado del request a Groq, reintentos y
validación de la respuesta contra LLMBatchResponse.

Ninguno le pega a Groq de verdad. Usamos `httpx.MockTransport`, inyectado
vía el parámetro `transport` de `analyze_batch`, en vez de parchear
`analyze_batch` o `httpx.AsyncClient.post` con unittest.mock: así se
ejercita el código REAL de armado del request, backoff y validación —el
punto de este módulo— y no solo la interfaz que expone hacia afuera.

`asyncio.sleep` se parchea a un no-op en los tests con reintentos, para no
esperar de verdad los ~3.5s de backoff exponencial en cada corrida de la
suite.
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import settings
from app.llm.client import LLMError, analyze_batch
from app.llm.models import AnalyzeItem

_ITEMS = [
    AnalyzeItem(external_id="1", copy_text="Buenísimo esto"),
    AnalyzeItem(external_id="2", copy_text="Una porquería"),
]


def _groq_body(results: list[dict]) -> dict:
    """Envoltorio "estilo OpenAI" que espera el código: el contenido real
    (el JSON que valida contra LLMBatchResponse) va serializado como
    string dentro de choices[0].message.content, tal como lo devuelve la
    API de chat completions de Groq.
    """
    return {"choices": [{"message": {"content": json.dumps({"results": results})}}]}


def _valid_results() -> list[dict]:
    return [
        {
            "index": 0,
            "sentiment": "positive",
            "sentiment_score": 0.8,
            "topics": ["general"],
            "rationale": "Tono positivo explícito.",
        },
        {
            "index": 1,
            "sentiment": "negative",
            "sentiment_score": -0.7,
            "topics": ["general"],
            "rationale": "Queja directa.",
        },
    ]


async def test_camino_feliz_devuelve_llmresults_validados():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_groq_body(_valid_results()))

    transport = httpx.MockTransport(handler)
    with patch.object(settings, "groq_api_key", "fake-key"):
        results = await analyze_batch(_ITEMS, transport=transport)

    assert len(results) == 2
    assert results[0].sentiment == "positive"
    assert results[1].sentiment == "negative"


async def test_sin_api_key_falla_rapido_sin_llamar_a_groq():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_groq_body(_valid_results()))

    transport = httpx.MockTransport(handler)
    with patch.object(settings, "groq_api_key", ""):
        with pytest.raises(LLMError, match="GROQ_API_KEY"):
            await analyze_batch(_ITEMS, transport=transport)

    assert called is False


async def test_todos_los_resultados_invalidos_reintenta_y_agota_intentos():
    """Caso límite en el que la validación item por item sigue teniendo que
    reintentar: si NINGÚN resultado del lote valida contra LLMResult, la
    respuesta es tan inservible como una que no parsea en absoluto (ver
    comentario en client.py).
    """
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # Los dos resultados vienen con sentiment_score fuera de rango:
        # LLMResult los rechaza a ambos, así que no queda ninguno válido.
        bad_results = [
            {
                "index": 0,
                "sentiment": "positive",
                "sentiment_score": 5.0,
                "topics": ["x"],
                "rationale": "r",
            },
            {
                "index": 1,
                "sentiment": "negative",
                "sentiment_score": -5.0,
                "topics": ["x"],
                "rationale": "r",
            },
        ]
        return httpx.Response(200, json=_groq_body(bad_results))

    transport = httpx.MockTransport(handler)
    with (
        patch.object(settings, "groq_api_key", "fake-key"),
        patch("app.llm.client.asyncio.sleep", new=AsyncMock()),
        pytest.raises(LLMError),
    ):
        await analyze_batch(_ITEMS, transport=transport)

    assert call_count == settings.llm_max_retries


async def test_un_resultado_invalido_no_tumba_el_lote_entero():
    """El corazón de la corrección: un solo resultado malformado (acá,
    sentiment_score fuera de [-1, 1]) no debe invalidar los otros
    resultados buenos del mismo lote. Se descarta el malo y se devuelven
    los que sí validan, SIN reintentar — service.py es quien se encarga de
    marcar como no analizado lo que falte.
    """
    call_count = 0
    items = [
        AnalyzeItem(external_id="1", copy_text="uno"),
        AnalyzeItem(external_id="2", copy_text="dos"),
        AnalyzeItem(external_id="3", copy_text="tres"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        results = [
            {
                "index": 0,
                "sentiment": "positive",
                "sentiment_score": 0.8,
                "topics": ["general"],
                "rationale": "ok",
            },
            {
                # sentiment_score fuera de rango: este item se descarta.
                "index": 1,
                "sentiment": "negative",
                "sentiment_score": -5.0,
                "topics": ["general"],
                "rationale": "malo",
            },
            {
                "index": 2,
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "topics": ["general"],
                "rationale": "ok",
            },
        ]
        return httpx.Response(200, json=_groq_body(results))

    transport = httpx.MockTransport(handler)
    with (
        patch.object(settings, "groq_api_key", "fake-key"),
        patch("app.llm.client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        results = await analyze_batch(items, transport=transport)

    assert call_count == 1
    mock_sleep.assert_not_called()
    assert {r.index for r in results} == {0, 2}


async def test_429_reintenta_y_termina_en_exito():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=_groq_body(_valid_results()))

    transport = httpx.MockTransport(handler)
    with (
        patch.object(settings, "groq_api_key", "fake-key"),
        patch("app.llm.client.asyncio.sleep", new=AsyncMock()),
    ):
        results = await analyze_batch(_ITEMS, transport=transport)

    assert call_count == 3
    assert len(results) == 2


async def test_fallo_permanente_no_duerme_backoff_en_el_ultimo_intento():
    """Ante un fallo que se repite en todos los intentos (acá, 500
    constante), el backoff se duerme entre intentos pero NO después del
    último: dormir ahí no compra ninguna chance extra de éxito, porque el
    loop termina y se levanta LLMError de todos modos. Con
    settings.llm_max_retries intentos hay max_retries - 1 backoffs, no
    max_retries.
    """
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    with (
        patch.object(settings, "groq_api_key", "fake-key"),
        patch("app.llm.client.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        pytest.raises(LLMError),
    ):
        await analyze_batch(_ITEMS, transport=transport)

    assert call_count == settings.llm_max_retries
    assert mock_sleep.call_count == settings.llm_max_retries - 1


async def test_401_no_reintenta():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="invalid api key")

    transport = httpx.MockTransport(handler)
    with (
        patch.object(settings, "groq_api_key", "fake-key"),
        patch("app.llm.client.asyncio.sleep", new=AsyncMock()),
        pytest.raises(LLMError, match="401"),
    ):
        await analyze_batch(_ITEMS, transport=transport)

    assert call_count == 1
