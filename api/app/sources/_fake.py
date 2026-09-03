"""Helpers compartidos por los adapters **mock** (mock_x, mock_instagram)
para generar datos falsos deterministas.

Los adapters reales de la Etapa 5 (Apify) no van a necesitar nada de esto:
sus datos vienen de afuera (la API real), no hay que inventarlos, así que
no hay semilla que sembrar ni fecha de referencia que anclar. Este módulo
es exclusivamente para simular una fuente.
"""

import hashlib
from datetime import datetime, timezone

FIRST_NAMES = [
    "juan", "martina", "lucas", "sofia", "nicolas", "valentina", "tomas",
    "camila", "franco", "julieta", "santiago", "agustina", "mateo",
    "florencia", "ignacio", "delfina", "bruno", "candela",
]


def seed_for(provider: str, tag: str) -> int:
    """Semilla determinista para (provider, tag): mismo par -> misma
    secuencia de datos generados, siempre, en cualquier proceso.

    Usamos hashlib.sha256 y NO hash() de Python a propósito: hash() de
    strings está aleatorizado por proceso (semillado con PYTHONHASHSEED),
    así que la misma corrida repetida en dos procesos distintos (o incluso
    el mismo proceso reiniciado) daría semillas distintas. Eso rompería
    justo lo que esta etapa necesita probar: que dos corridas del pipeline
    con el mismo tag traen los mismos external_id, para poder verificar la
    idempotencia real vía el UNIQUE (provider, external_id) de Postgres.
    """
    digest = hashlib.sha256(f"{provider}:{tag}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def today_utc_midnight() -> datetime:
    """Ancla del rango "últimos ~7 días" a la medianoche UTC del día actual.

    No usamos datetime.now(timezone.utc) directo como ancla porque dos
    llamadas a search() con microsegundos de diferencia darían
    published_at ligeramente distintos y romperían el test de determinismo.
    Redondear al día alcanza para el propósito de este mock (datos
    "recientes" para la demo) sin sacrificar la reproducibilidad dentro del
    mismo día.
    """
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
