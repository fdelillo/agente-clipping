"""Tests de app/llm/service.py: batching, reasociación de índices con
external_id y degradación ante fallas parciales.

Acá sí parcheamos `app.llm.service.analyze_batch` (con AsyncMock) en vez de
mockear HTTP: la responsabilidad de este módulo es la orquestación, no el
protocolo con Groq (eso ya lo cubre test_llm_client.py), así que lo que nos
interesa controlar es qué devuelve el cliente, no cómo llega a devolverlo.

Salvo en el test que prueba explícitamente el caso "sin key", todos los
demás fuerzan `settings.groq_api_key` a un valor no vacío: el chequeo de
`ensure_configured()` al principio de `analyze_items` es real (no está
mockeado acá) y sin esto los tests dependerían de si GROQ_API_KEY está
cargada en el .env de quien corre la suite, que es justo lo que no
queremos.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.llm.client import LLMError
from app.llm.models import AnalyzeItem, LLMResult
from app.llm.service import analyze_items


def _item(n: int) -> AnalyzeItem:
    return AnalyzeItem(external_id=f"ext-{n}", copy_text=f"copy {n}")


def _result(index: int, sentiment: str = "neutral") -> LLMResult:
    return LLMResult(
        index=index,
        sentiment=sentiment,
        sentiment_score=0.0,
        topics=["general"],
        rationale="r",
    )


async def test_camino_feliz_mapea_todos_los_campos():
    items = [_item(1), _item(2)]
    llm_results = [
        _result(0, "positive"),
        _result(1, "negative"),
    ]
    with (
        patch("app.llm.service.analyze_batch", new=AsyncMock(return_value=llm_results)),
        patch.object(settings, "groq_api_key", "fake-key"),
    ):
        results = await analyze_items(items)

    assert len(results) == 2
    assert results[0].external_id == "ext-1"
    assert results[0].analyzed is True
    assert results[0].sentiment == "positive"
    assert results[0].analyzed_at is not None
    assert results[1].external_id == "ext-2"
    assert results[1].sentiment == "negative"


async def test_menos_resultados_que_items_asocia_bien_los_presentes():
    """El test importante: si el modelo devuelve menos results de los que
    se le mandaron, el/los que faltan salen analyzed=False y los que SÍ
    llegaron quedan pegados al external_id correcto (no al que le tocaría
    por posición en la lista de salida).
    """
    items = [_item(1), _item(2), _item(3)]
    # Solo contesta para el índice 2 (el tercer item, "ext-3"). Si la
    # reasociación fuera por posición en vez de por índice, este resultado
    # terminaría mal pegado al primer item de la lista de análisis.
    llm_results = [_result(2, "positive")]
    with (
        patch("app.llm.service.analyze_batch", new=AsyncMock(return_value=llm_results)),
        patch.object(settings, "groq_api_key", "fake-key"),
    ):
        results = await analyze_items(items)

    by_external_id = {r.external_id: r for r in results}
    assert by_external_id["ext-1"].analyzed is False
    assert by_external_id["ext-1"].error is not None
    assert by_external_id["ext-2"].analyzed is False
    assert by_external_id["ext-3"].analyzed is True
    assert by_external_id["ext-3"].sentiment == "positive"


async def test_indice_no_enviado_se_descarta_sin_corromper_nada():
    items = [_item(1)]
    # El modelo devuelve un índice (5) que nunca existió en el batch.
    llm_results = [_result(5, "positive")]
    with (
        patch("app.llm.service.analyze_batch", new=AsyncMock(return_value=llm_results)),
        patch.object(settings, "groq_api_key", "fake-key"),
    ):
        results = await analyze_items(items)

    assert len(results) == 1
    assert results[0].external_id == "ext-1"
    assert results[0].analyzed is False


async def test_batching_respeta_llm_batch_size():
    items = [_item(n) for n in range(25)]
    mock_analyze_batch = AsyncMock(
        side_effect=lambda batch: [_result(i, "neutral") for i in range(len(batch))]
    )
    with (
        patch("app.llm.service.analyze_batch", new=mock_analyze_batch),
        patch.object(settings, "llm_batch_size", 10),
        patch.object(settings, "groq_api_key", "fake-key"),
    ):
        results = await analyze_items(items)

    assert mock_analyze_batch.call_count == 3
    call_sizes = [len(call.args[0]) for call in mock_analyze_batch.call_args_list]
    assert call_sizes == [10, 10, 5]
    assert len(results) == 25
    assert all(r.analyzed for r in results)


async def test_un_lote_falla_y_otro_no_da_respuesta_parcial_correcta():
    items = [_item(n) for n in range(15)]

    async def fake_analyze_batch(batch):
        # El primer lote (items 0..9) falla; el segundo (10..14) anda bien.
        if batch[0].external_id == "ext-0":
            raise LLMError("Groq caído para este lote")
        return [_result(i, "neutral") for i in range(len(batch))]

    with (
        patch("app.llm.service.analyze_batch", new=AsyncMock(side_effect=fake_analyze_batch)),
        patch.object(settings, "llm_batch_size", 10),
        patch.object(settings, "groq_api_key", "fake-key"),
    ):
        results = await analyze_items(items)

    failed = [r for r in results if not r.analyzed]
    analyzed = [r for r in results if r.analyzed]
    assert len(failed) == 10
    assert len(analyzed) == 5
    assert all(r.error is not None for r in failed)


async def test_sin_api_key_levanta_llmerror_sin_intentar_ningun_lote():
    mock_analyze_batch = AsyncMock()
    with (
        patch.object(settings, "groq_api_key", ""),
        patch("app.llm.service.analyze_batch", new=mock_analyze_batch),
    ):
        with pytest.raises(LLMError, match="GROQ_API_KEY"):
            await analyze_items([_item(1)])

    mock_analyze_batch.assert_not_called()
