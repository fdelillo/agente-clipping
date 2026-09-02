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

    # Opcional en esta etapa (Etapa 0 no llama al LLM todavía). Se vuelve
    # relevante recién en la Etapa 2.
    groq_api_key: str = ""

    # Carpeta compartida con n8n (montada como ./compartido:/data en
    # docker-compose.yml), donde la api va a dejar los informes generados.
    shared_dir: str = "/data"


settings = Settings()
