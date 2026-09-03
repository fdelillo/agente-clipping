"""Endpoints de captura de menciones (Etapa 1).

Capa fina sobre el registry de app/sources: valida que el provider exista y
que los parámetros de búsqueda tengan una forma razonable, delega la
búsqueda al adapter correspondiente y envuelve el resultado en
`SearchResponse`. A propósito no hay lógica de negocio acá (normalización,
generación de datos): eso vive en los adapters, este módulo solo enruta.
"""

from fastapi import APIRouter, HTTPException, Query

from app.models import SearchResponse
from app.sources import available_providers, get_adapter

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
async def list_sources() -> list[str]:
    return available_providers()


@router.get("/{provider}/search", response_model=SearchResponse)
async def search(
    provider: str,
    tag: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="Tag o keyword a buscar (ej: nombre de marca, hashtag sin el #).",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Cantidad máxima de menciones a devolver.",
    ),
) -> SearchResponse:
    adapter = get_adapter(provider)
    if adapter is None:
        # 404 y no 422/500: el provider es parte de la ruta (un recurso que
        # puede no existir), no un parámetro mal formado. El detail incluye
        # los providers disponibles para que quien llama (n8n, en la
        # práctica) no tenga que ir a mirar el código para saber qué valores
        # son válidos.
        raise HTTPException(
            status_code=404,
            detail=f"Proveedor '{provider}' no existe. Disponibles: {available_providers()}",
        )
    mentions = await adapter.search(tag=tag, limit=limit)
    return SearchResponse(provider=provider, tag=tag, count=len(mentions), mentions=mentions)
