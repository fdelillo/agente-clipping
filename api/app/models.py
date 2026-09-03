"""Modelos Pydantic del dominio: esquema común y formas crudas de cada fuente.

`Mention` es el contrato de salida de cualquier adapter (ver app/sources/) y
lo que termina consumiendo n8n. Deliberadamente NO incluye los campos de
análisis del LLM (sentiment, sentiment_score, topics, llm_rationale,
analyzed_at) ni el `id` autogenerado de Postgres, aunque ambos existan en la
tabla `mentions` (ver db/init/001_schema.sql). La razón: `Mention` representa
"lo que devuelve una fuente" en el momento de la captura, cuando todavía no
se llamó al LLM. El análisis llega recién en la Etapa 2 como un objeto
aparte (la respuesta de POST /analyze), y es n8n quien hace el merge entre
la mención capturada y su análisis antes de insertar la fila completa en
Postgres. Meter esos campos acá obligaría a la API a inventar valores nulos
o falsos para algo que todavía no pasó.

`RawXPost` y `RawInstagramPost` son las formas CRUDAS que cada fuente
devuelve tal cual, antes de normalizar. Son deliberadamente distintas entre
sí — una anidada en snake_case, la otra plana en camelCase; una sin
permalink (hay que construirlo), la otra con él; "text" vs. "caption" —
porque esa es la forma real de la API v2 de X y del scraper de Apify para
Instagram respectivamente. Si las hubiéramos modelado iguales, normalizar
sería un ejercicio de mentira: la Etapa 1 tiene que dejar el trabajo de
mapeo hecho de verdad para que la Etapa 5 (fuente real) no traiga sorpresas.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Mention(BaseModel):
    """Esquema común normalizado: lo que devuelve cualquier `SourceAdapter`.

    Espejo de la tabla `mentions`, pero sin los campos de análisis del LLM
    ni el `id` de la base (ver el docstring del módulo para el motivo).
    """

    provider: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    author_handle: str | None = None
    copy_text: str | None = None
    permalink: str | None = None
    published_at: datetime | None = None
    # Cada red expone métricas distintas (ver comentario sobre jsonb en
    # db/init/001_schema.sql); default_factory=dict y no un default mutable
    # compartido entre instancias, que es el error clásico de Python.
    metrics: dict[str, Any] = Field(default_factory=dict)
    # Siempre timezone-aware: datetime.utcnow() está deprecado y devuelve un
    # datetime naive, lo que más adelante explota al compararlo con uno
    # aware (como published_at, que sí trae tz). now(timezone.utc) es la
    # forma correcta.
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RawXAuthor(BaseModel):
    """Autor tal como lo expande la API v2 de X dentro de `includes.users`."""

    id: str
    username: str
    name: str


class RawXMetrics(BaseModel):
    """Métricas públicas de un tweet, tal como las expone `public_metrics`."""

    retweet_count: int
    reply_count: int
    like_count: int
    quote_count: int
    impression_count: int


class RawXPost(BaseModel):
    """Forma cruda de un tweet, tal como la expone la API v2 de X (y el
    scraper de Apify que la imita para no depender de credenciales oficiales).

    Ojo: esta forma NO trae permalink. Hay que construirlo en la
    normalización como `https://x.com/{username}/status/{id}`, combinando
    dos campos que acá viven en objetos distintos (`id` del post, `username`
    del autor anidado).
    """

    id: str
    text: str
    created_at: datetime
    lang: str | None = None
    author: RawXAuthor
    public_metrics: RawXMetrics


class RawInstagramPost(BaseModel):
    """Forma cruda de un post de Instagram, tal como la expone el scraper de
    Apify: plana (sin objetos anidados) y en camelCase, a diferencia de la
    de X.

    Los nombres de atributo en Python quedan en snake_case (idiomático) con
    `alias` apuntando al nombre real en camelCase que trae el JSON de
    origen; `populate_by_name=True` permite además instanciar el modelo
    usando el nombre en snake_case directamente (lo usan los generadores
    mock, que arman el objeto a mano en vez de parsear JSON externo).
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    short_code: str = Field(alias="shortCode")
    caption: str | None = None
    timestamp: datetime
    owner_username: str = Field(alias="ownerUsername")
    likes_count: int = Field(alias="likesCount")
    comments_count: int = Field(alias="commentsCount")
    # None cuando el post no es un video (Image, Sidecar sin video).
    video_view_count: int | None = Field(default=None, alias="videoViewCount")
    type: str  # "Video" | "Image" | "Sidecar"
    url: str  # a diferencia de X, acá el permalink sí viene incluido.


class SearchResponse(BaseModel):
    """Respuesta de `GET /sources/{provider}/search`.

    Se envuelve en un objeto en vez de devolver una lista pelada por dos
    motivos: deja lugar para sumar paginación o metadata más adelante sin
    romper el contrato existente, y del lado de n8n obliga a usar el nodo
    "Split Out" sobre el campo `mentions` en vez de asumir que la respuesta
    entera es un array — que es el patrón correcto para consumir listas
    dentro de un workflow de n8n.
    """

    provider: str
    tag: str
    count: int
    mentions: list[Mention]
