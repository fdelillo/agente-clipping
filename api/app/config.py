"""Configuración de la API, leída de variables de entorno.

Usamos pydantic-settings en vez de os.environ a mano porque valida tipos y
centraliza en un solo lugar qué variables espera la app — si falta una
obligatoria, falla rápido al arrancar en vez de explotar más tarde en medio
de un request.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Obligatoria: sin esto la api no tiene con qué conectarse a Postgres.
    database_url: str

    # Opcional a nivel tipos (así la app arranca sin ella), pero
    # obligatoria en la práctica para que POST /analyze funcione: sin
    # key, app/llm/client.py falla con un mensaje explicando qué falta en
    # vez de un 401 críptico de Groq (ver ese módulo).
    groq_api_key: str = ""

    # Modelo de Groq para clasificar sentimiento/temas (Etapa 2).
    # Configurable porque el catálogo de modelos disponibles en Groq
    # cambia con cierta frecuencia y no queremos que eso implique tocar
    # código, solo la variable de entorno.
    groq_model: str = "llama-3.3-70b-versatile"

    # Timeout explícito del cliente httpx contra Groq. El default de
    # AsyncClient sin argumentos ya trae un timeout razonable, pero
    # preferimos fijarlo nosotros desde settings en vez de heredar el
    # default de la librería, que puede cambiar de versión a versión sin
    # que nos demos cuenta. 30s es holgado para un batch de ~20 copies.
    groq_timeout_seconds: float = 30.0

    # Cuántos copies van en una sola llamada al LLM (ver
    # app/llm/service.py). El rate limit de Groq es por minuto: mandar 50
    # menciones en 50 requests lo agota en segundos. 20 es un punto medio
    # razonable entre "pocas llamadas" y "prompt no gigante".
    llm_batch_size: int = 20

    # Reintentos ante fallas transitorias (red, 5xx, 429, JSON que no
    # valida contra el esquema esperado) antes de marcar un lote entero
    # como no analizado. Ver app/llm/client.py para el detalle de qué SÍ y
    # qué NO se reintenta.
    llm_max_retries: int = 3

    # Carpeta compartida con n8n (montada como ./compartido:/data en
    # docker-compose.yml), donde la api va a dejar los informes generados.
    shared_dir: str = "/data"


settings = Settings()
