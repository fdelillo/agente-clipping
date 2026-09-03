"""Endpoint de análisis de menciones con LLM (Etapa 2).

POST /analyze NO toca Postgres: recibe copies (external_id + copy_text,
tal cual salieron de GET /sources/{provider}/search) y devuelve su
análisis de sentimiento/temas. No conoce ids de fila de la base ni escribe
nada — es n8n quien hace el merge entre la mención capturada (que sí trae
provider/external_id) y este análisis con un nodo Merge, antes del INSERT
final en Postgres. Es una decisión deliberada (ver PLAN.md §5 y §9): deja a
la API sin estado de negocio en este endpoint y le da al workflow de n8n un
nodo Merge real que resolver, en vez de que la API le entregue a n8n una
mención ya enriquecida y lo deje como un cron tonto.
"""

from fastapi import APIRouter, HTTPException

from app.llm.client import LLMError
from app.llm.models import AnalyzeRequest, AnalyzeResponse
from app.llm.service import analyze_items

router = APIRouter(tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        results = await analyze_items(request.items)
    except LLMError as exc:
        # analyze_items atrapa el LLMError de cada lote fallido y lo
        # convierte en items analyzed=False (ver app/llm/service.py) — así
        # que si un LLMError llega hasta acá es porque ni siquiera se pudo
        # INTENTAR el primer lote, por GROQ_API_KEY ausente. Eso sí es un
        # problema del servicio (no del contenido del request ni de una
        # falla puntual de Groq analizando texto) y corresponde 503, no un
        # 200 con failed_count == count que escondería un problema de
        # configuración detrás de una respuesta con forma de éxito parcial.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    analyzed_count = sum(1 for r in results if r.analyzed)
    failed_count = len(results) - analyzed_count
    return AnalyzeResponse(
        count=len(results),
        analyzed_count=analyzed_count,
        failed_count=failed_count,
        results=results,
    )
