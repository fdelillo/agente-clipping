"""Orquesta el análisis de un batch de menciones: parte la lista de entrada
en lotes, llama al cliente de Groq lote por lote y re-asocia cada
resultado con el `external_id` del item que lo originó.

Esta es la capa que "degrada con gracia" que pide el plan: ni un lote
entero fallido ni una alucinación de índices tumban el request completo —
ver el comentario sobre la validación de índices más abajo, que es el punto
más delicado de todo el módulo.
"""

from datetime import datetime, timezone

from app.config import settings
from app.llm.client import LLMError, analyze_batch, ensure_configured
from app.llm.models import Analysis, AnalyzeItem, LLMResult


async def analyze_items(items: list[AnalyzeItem]) -> list[Analysis]:
    # Chequeo temprano, antes de intentar el primer lote: sin
    # GROQ_API_KEY, TODOS los lotes van a fallar exactamente de la misma
    # manera, así que no tiene sentido dejar que cada uno lo descubra y lo
    # reporte por separado (y de paso demore el error con reintentos que
    # sabemos de antemano que no van a servir). Elevamos el LLMError tal
    # cual hasta el router (app/routers/analyze.py), que lo traduce en un
    # 503: es un problema de configuración del servicio, no un resultado
    # parcial que tenga sentido devolver como 200.
    ensure_configured()

    results: list[Analysis] = []
    for start in range(0, len(items), settings.llm_batch_size):
        batch = items[start : start + settings.llm_batch_size]
        results.extend(await _analyze_one_batch(batch))
    return results


async def _analyze_one_batch(batch: list[AnalyzeItem]) -> list[Analysis]:
    try:
        llm_results = await analyze_batch(batch)
    except LLMError as exc:
        # El lote agotó sus reintentos (red caída, Groq devolviendo 5xx
        # sostenido, JSON que nunca valida, etc.). A esta altura ya
        # sabemos que la key está configurada (ensure_configured() pasó en
        # analyze_items), así que esto es una falla real del lote, no de
        # config: no propagamos. Los demás lotes del request siguen su
        # curso normalmente, y este sale marcado item por item con el
        # motivo, para que el resto del análisis no se pierda por un lote
        # puntual.
        return [
            Analysis(external_id=item.external_id, analyzed=False, error=str(exc))
            for item in batch
        ]

    # --- El chequeo más importante del módulo -------------------------
    # `LLMResult.index` es la posición DENTRO DE ESTE LOTE que le
    # asignamos al copy en app/llm/prompts.py:build_user_prompt (0-based,
    # 0..len(batch)-1). Ahí es exactamente donde una alucinación del LLM
    # podría pegar el análisis de un copy a la mención equivocada: si
    # confiáramos en el ORDEN de la lista que devuelve Groq en vez de en
    # el índice explícito que declaró cada resultado, un sentiment
    # "negative" podría terminar asociado al external_id de un posteo
    # completamente distinto sin que nada lo detecte — el peor tipo de bug
    # posible acá, porque no rompe nada visiblemente, solo guarda un dato
    # incorrecto con total confianza.
    #
    # Por eso mapeamos por índice explícito y descartamos cualquier
    # resultado cuyo índice esté fuera de rango (el modelo inventó un
    # número que no le mandamos) o repetido (ya vimos ese índice antes: nos
    # quedamos con el primero y el resto se ignora, en vez de dejar que el
    # último pise al anterior en silencio).
    by_index: dict[int, LLMResult] = {}
    for llm_result in llm_results:
        if 0 <= llm_result.index < len(batch) and llm_result.index not in by_index:
            by_index[llm_result.index] = llm_result

    now = datetime.now(timezone.utc)
    analyses: list[Analysis] = []
    for i, item in enumerate(batch):
        llm_result = by_index.get(i)
        if llm_result is None:
            # O el modelo se saltó este índice, o vino con un índice
            # inválido que descartamos arriba: cualquiera de los dos casos
            # termina igual, sin inventar un análisis para lo que no
            # llegó.
            analyses.append(
                Analysis(
                    external_id=item.external_id,
                    analyzed=False,
                    error="El modelo no devolvió un resultado válido para este item.",
                )
            )
            continue
        analyses.append(
            Analysis(
                external_id=item.external_id,
                analyzed=True,
                sentiment=llm_result.sentiment,
                sentiment_score=llm_result.sentiment_score,
                topics=llm_result.topics,
                llm_rationale=llm_result.rationale,
                # Solo se setea en los items efectivamente analizados. En
                # los fallidos queda None (default de Analysis), que es lo
                # que deja la fila en Postgres con analyzed_at IS NULL y
                # elegible para un barrido posterior por
                # idx_mentions_analyzed_at (ver db/init/001_schema.sql).
                analyzed_at=now,
            )
        )
    return analyses
