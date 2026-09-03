"""Modelos Pydantic del análisis con LLM (Etapa 2).

Viven en app/llm/ y no en app/models.py a propósito: app/models.py es el
contrato de captura (Mention y las formas RAW de cada fuente), estable
desde la Etapa 1 y con su propio docstring explicando por qué NO incluye
nada de análisis. Los modelos de acá son el contrato del análisis —piden
copies de entrada, hablan el formato de batch de Groq, devuelven sentiment
por item— y van a seguir moviéndose mientras se itera el prompt (ver
app/llm/prompts.py). Separarlos en su propio subpaquete, con el mismo
criterio que ya usa app/sources/ para los adapters, evita que
app/models.py termine mezclando dos responsabilidades que cambian por
razones distintas.

Los nombres de campo de `Analysis` coinciden 1 a 1 con las columnas que la
Etapa 2 le suma a `mentions` (sentiment, sentiment_score, topics,
llm_rationale, analyzed_at; ver db/init/001_schema.sql) a propósito: es lo
que le permite al nodo Postgres de n8n mapear la respuesta de /analyze
directo a columnas del INSERT, sin un nodo Set intermedio que renombre
campos a mano.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeItem(BaseModel):
    """Lo que entra a /analyze por cada mención a clasificar. Deliberadamente
    mínimo: solo lo que el LLM necesita para analizar (external_id para
    poder reasociar el resultado después, copy_text para clasificar). No
    lleva provider ni el resto de los campos de Mention porque /analyze no
    los usa ni los devuelve — es n8n quien vuelve a juntar todo (ver
    docstring de app/routers/analyze.py).
    """

    external_id: str = Field(min_length=1)
    copy_text: str


class AnalyzeRequest(BaseModel):
    # max_length=100: tope defensivo del lado del request. Ya batcheamos
    # internamente en tandas más chicas (ver app/llm/service.py), pero sin
    # este límite un caller mal configurado podría mandar miles de items en
    # un solo POST y armar decenas de llamadas al LLM de un tirón, sin
    # ningún control de por medio.
    items: list[AnalyzeItem] = Field(min_length=1, max_length=100)


class LLMResult(BaseModel):
    """Lo que el modelo tiene que devolver por cada copy. Estos constraints
    son la red que atrapa una alucinación antes de que llegue a Postgres:
    si el modelo inventa un sentiment que no es de los tres valores
    esperados, o un score fuera de [-1, 1], Pydantic lo rechaza acá y
    app/llm/client.py lo trata como una respuesta inválida (reintentable),
    no como un dato que hay que guardar tal cual vino.
    """

    index: int
    sentiment: Literal["positive", "neutral", "negative"]
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    topics: list[str]
    rationale: str


class LLMBatchResponse(BaseModel):
    """Valida SOLO la envoltura de la respuesta de Groq: que el JSON sea un
    objeto con una clave "results" que sea una lista de objetos. A
    propósito NO valida la forma de cada elemento (por eso `results` es
    `list[dict]` y no `list[LLMResult]`) — esa validación pasó a hacerse
    ítem por ítem en app/llm/client.py, para que un solo resultado
    malformado no invalide el lote entero (ver el comentario ahí). Envolver
    en "results" y no devolver una lista pelada es una costumbre de la API
    de OpenAI-compatible que Groq imita: el modelo tiende a respetar mejor
    un objeto JSON con una clave nombrada que un array top-level cuando se
    le pide `json_object`.
    """

    results: list[dict]


class Analysis(BaseModel):
    """Salida de /analyze por item. Nombres de campo == columnas de
    `mentions` (ver docstring del módulo)."""

    external_id: str
    analyzed: bool
    sentiment: str | None = None
    sentiment_score: float | None = None
    topics: list[str] | None = None
    llm_rationale: str | None = None
    # None en los items fallidos: es justamente lo que después, ya en
    # Postgres, deja la fila con analyzed_at IS NULL y elegible para un
    # barrido posterior por idx_mentions_analyzed_at (ver
    # db/init/001_schema.sql).
    analyzed_at: datetime | None = None
    # Motivo de la falla cuando analyzed=False (lote entero caído, índice
    # sin match, etc.). No es una columna de `mentions` -no tiene sentido
    # persistirlo en la tabla- pero viaja en la respuesta HTTP porque es
    # justo lo que n8n necesita loguear para diagnosticar sin ir a buscar
    # los logs de la API.
    error: str | None = None


class AnalyzeResponse(BaseModel):
    count: int
    analyzed_count: int
    failed_count: int
    results: list[Analysis]
