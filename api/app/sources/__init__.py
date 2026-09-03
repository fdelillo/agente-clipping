"""Registry de adapters de fuentes disponibles.

Es el único lugar donde la API sabe qué proveedores existen. Agregar la
fuente real en la Etapa 5 (`apify_x`, `apify_instagram`) es sumar una
entrada acá con un adapter que cumpla el mismo `SourceAdapter`; del lado de
n8n lo único que cambia es el nombre del provider en la URL del HTTP
Request (`/sources/apify_x/search` en vez de `/sources/mock_x/search`).
Nada más del workflow se toca.
"""

from app.sources.base import SourceAdapter
from app.sources.mock_instagram import adapter as mock_instagram_adapter
from app.sources.mock_x import adapter as mock_x_adapter

_REGISTRY: dict[str, SourceAdapter] = {
    mock_x_adapter.name: mock_x_adapter,
    mock_instagram_adapter.name: mock_instagram_adapter,
}


def get_adapter(name: str) -> SourceAdapter | None:
    """None si el provider no existe, en vez de levantar: quien llama (el
    router) decide qué código de estado corresponde, esta función no sabe
    de HTTP.
    """
    return _REGISTRY.get(name)


def available_providers() -> list[str]:
    return list(_REGISTRY.keys())
