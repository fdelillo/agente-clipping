"""Cliente HTTP de la API de Groq (chat completions), usado por
app/llm/service.py para clasificar sentimiento y temas de los copies
capturados.

Usamos httpx a mano en vez del SDK oficial `groq`: httpx ya es dependencia
del proyecto (la sigue necesitando el resto de la API), y para pegarle a un
único endpoint no vale la pena sumar y mantener otra dependencia externa
con su propio ciclo de versiones y su propia superficie de bugs. El SDK
oficial no nos ahorra nada acá que valga ese costo.

Reintentos: hasta `settings.llm_max_retries` intentos con backoff
exponencial, pero SOLO ante fallas que un reintento puede arreglar: error
de red/timeout, HTTP 5xx (problema transitorio del lado de Groq), HTTP 429
(rate limit — esperar y reintentar es literalmente la respuesta correcta),
una respuesta que ni siquiera tiene la forma de sobre esperada (un objeto
con "results" como lista — el modelo alucinó algo irreconocible), y el caso
límite en que NINGÚN resultado del lote validó contra `LLMResult`. Fuera de
ese último caso, la validación de cada resultado es item por item, no
todo-o-nada: si algunos resultados validan y otros no, devolvemos los
válidos y dejamos que app/llm/service.py degrade los faltantes (ver el
comentario en `analyze_batch`). Un 4xx que NO sea 429 (401 por key
inválida, 400 por request mal formado) NO se reintenta: son errores de
configuración o del request, no algo que el paso del tiempo resuelva —
reintentar tres veces un 401 solo demora el error y quema cupo de rate
limit para nada.
"""

import asyncio
import json

import httpx
from pydantic import ValidationError

from app.config import settings
from app.llm.models import AnalyzeItem, LLMBatchResponse, LLMResult
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Backoff exponencial arrancando en medio segundo: 0.5s, 1s, 2s entre los 3
# intentos por default. Groq expone un header Retry-After en el 429 que
# sería más preciso respetar, pero a la escala de esta fase (un puñado de
# lotes por corrida de n8n) un backoff fijo alcanza y es bastante más
# simple de razonar y de testear.
_RETRY_BASE_DELAY_SECONDS = 0.5

_MISSING_KEY_MESSAGE = (
    "GROQ_API_KEY no está configurada. Cargala en .env (se obtiene gratis "
    "en console.groq.com) y reiniciá la API."
)


class LLMError(Exception):
    """Se agotaron los reintentos contra Groq, o el error no era
    reintentable en primer lugar (ver docstring del módulo)."""


def ensure_configured() -> None:
    """Chequeo compartido con app/llm/service.py (que lo llama una sola vez
    por request, antes de intentar el primer lote — ver ese módulo). Vive
    acá y no repetido en cada lugar porque el mensaje accionable es el
    mismo y no queremos que diverja con el tiempo.
    """
    if not settings.groq_api_key:
        # Fallamos acá, antes de armar siquiera el request, con un mensaje
        # que dice exactamente qué falta. La alternativa —dejar que Groq
        # devuelva su propio 401— es un error críptico para quien lo lea en
        # el log de n8n sin tener el código delante.
        raise LLMError(_MISSING_KEY_MESSAGE)


async def analyze_batch(
    items: list[AnalyzeItem], *, transport: httpx.AsyncBaseTransport | None = None
) -> list[LLMResult]:
    """Manda UN lote (todos los `items`) en una sola llamada al LLM y
    devuelve los `LLMResult` que Groq contestó, ya validados. No hace
    reasociación con external_id ni maneja índices faltantes/inventados —
    eso es trabajo de app/llm/service.py, que sabe de dónde salió cada
    item; acá solo hablamos HTTP con Groq.

    `transport` es un hook de testeo: `httpx.MockTransport` se lo puede
    pasar a `httpx.AsyncClient` para simular respuestas de Groq sin pegarle
    a la red de verdad, ejercitando el código real de armado de request,
    reintentos y validación (no un mock del método `analyze_batch` en sí).
    En producción queda en None y httpx usa el transport real.
    """
    ensure_configured()

    user_prompt = build_user_prompt(items)
    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        # Fuerza que el body de respuesta sea JSON sintácticamente válido.
        # Eso NO garantiza que su contenido cumpla el esquema que pedimos
        # en el prompt (podría faltarle un campo, "results" podría no ser
        # una lista) — por eso más abajo igual validamos con
        # LLMBatchResponse antes de confiar en nada.
        "response_format": {"type": "json_object"},
        # Temperatura baja: esto es clasificación (sentimiento/temas), no
        # generación creativa. Queremos que el mismo copy tienda a dar
        # siempre el mismo veredicto entre corridas, no variedad de estilo.
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}

    last_error: Exception | None = None
    # Timeout explícito: el default de httpx.AsyncClient sin argumentos NO
    # es infinito por suerte (son 5s), pero igual lo fijamos a propósito
    # desde settings en vez de confiar en el default de la librería, que
    # podría cambiar de versión a versión sin que nos demos cuenta.
    async with httpx.AsyncClient(
        timeout=settings.groq_timeout_seconds, transport=transport
    ) as client:
        for attempt in range(settings.llm_max_retries):
            # No tiene sentido dormir el backoff cuando este era el último
            # intento disponible: el loop termina igual y ese sleep (hasta
            # ~2s con los defaults) solo demora el LLMError que vamos a
            # levantar de todos modos, sin ganar ninguna chance extra de
            # éxito. Por eso cada rama de error de acá abajo chequea
            # `is_last_attempt` antes de llamar a `_backoff`.
            is_last_attempt = attempt == settings.llm_max_retries - 1
            try:
                response = await client.post(_GROQ_URL, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                if not is_last_attempt:
                    await _backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = LLMError(
                    f"Groq devolvió {response.status_code}: {response.text[:200]}"
                )
                if not is_last_attempt:
                    await _backoff(attempt)
                continue

            if response.status_code >= 400:
                # 4xx que no es 429: no reintentable (ver docstring del
                # módulo). Cortamos ahí mismo en vez de agotar los 3
                # intentos con el mismo error garantizado.
                raise LLMError(
                    f"Groq devolvió {response.status_code} (no reintentable): "
                    f"{response.text[:200]}"
                )

            try:
                raw_content = response.json()["choices"][0]["message"]["content"]
                envelope = LLMBatchResponse.model_validate_json(raw_content)
            except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
                # ValueError cubre pydantic.ValidationError (es subclase) y
                # cualquier json.JSONDecodeError que no haya caído ya en el
                # except explícito. Acá la respuesta ni siquiera tiene la
                # forma de sobre esperada (un objeto con "results" como
                # lista) — eso sí es una respuesta inservible de punta a
                # punta, no algo que se pueda salvar item por item.
                # Reintentable, no necesariamente un bug nuestro.
                last_error = LLMError(f"Respuesta de Groq no tiene la forma esperada: {exc}")
                if not is_last_attempt:
                    await _backoff(attempt)
                continue

            # --- Validación item por item, no todo-o-nada -----------------
            # Antes acá validábamos el lote entero de una con
            # `LLMBatchResponse.model_validate_json`, que exigía que TODOS
            # los resultados cumplieran `LLMResult` (Literal en sentiment,
            # ge/le en sentiment_score) para aceptar cualquiera de ellos.
            # Eso significaba que UNA sola alucinación puntual (ej. un
            # sentiment_score: 1.5 en un solo item de 20) invalidaba los
            # otros 19 resultados buenos y mandaba a reintentar el lote
            # completo sin necesidad. Es innecesario porque
            # app/llm/service.py YA sabe degradar item por item: cuando un
            # índice no aparece entre los resultados que devolvemos acá, ese
            # item sale analyzed=False con su motivo, sin afectar al resto
            # del lote. Entonces acá validamos cada resultado por separado,
            # nos quedamos con los que sí validan, y dejamos que
            # service.py se encargue de los índices faltantes exactamente
            # como ya hace con índices ausentes o repetidos.
            valid_results: list[LLMResult] = []
            for raw_result in envelope.results:
                try:
                    valid_results.append(LLMResult.model_validate(raw_result))
                except ValidationError:
                    # Descartamos el item inválido sin abortar el lote. No
                    # logueamos el detalle a propósito: es una alucinación
                    # puntual y esperable del modelo, no un caso que
                    # necesite ruido en los logs.
                    continue

            if not valid_results:
                # Ni un solo resultado validó: la respuesta es tan inútil
                # como una que no parsea en absoluto (ver el except de
                # arriba), así que el criterio es el mismo acá — reintentar.
                last_error = LLMError(
                    "Ningún resultado del lote validó contra LLMResult "
                    f"(el modelo devolvió {len(envelope.results)} objetos, todos inválidos)."
                )
                if not is_last_attempt:
                    await _backoff(attempt)
                continue

            # Al menos un resultado validó: devolvemos lo que hay. Los
            # índices faltantes (los que el modelo no mandó, o mandó
            # inválidos y acabamos de descartar arriba) los resuelve
            # app/llm/service.py marcándolos analyzed=False.
            return valid_results

    raise LLMError(
        f"Se agotaron los {settings.llm_max_retries} intentos contra Groq. "
        f"Último error: {last_error}"
    )


async def _backoff(attempt: int) -> None:
    await asyncio.sleep(_RETRY_BASE_DELAY_SECONDS * (2**attempt))
