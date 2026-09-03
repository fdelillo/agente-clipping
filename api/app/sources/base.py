"""Interfaz común que deben cumplir los adapters de fuentes.

Se modela como `typing.Protocol` (tipado estructural) y no como una clase
abstracta con herencia: un adapter no necesita heredar de nada ni llamar a
`super().__init__()`, alcanza con que tenga el atributo `name` y un método
`search` con esta firma exacta. Esto lo hace más fácil de testear (un mock o
un stub que ni siquiera importa este módulo ya "cumple" el Protocol) y evita
acoplar los adapters a una jerarquía de clases que en este proyecto no
aporta nada.

`search` es `async` aunque los adapters mock de esta etapa no hagan I/O real
(generan datos en memoria). La fuente real de la Etapa 5 va a pegarle a
Apify por HTTP con httpx, que sí es asíncrono, y no queremos tener que
cambiar esta firma —y por lo tanto el registry en app/sources/__init__.py y
el router en app/routers/sources.py— cuando eso pase. Mejor pagar el
`async def` de más ahora que romper el contrato después.
"""

from typing import Protocol

from app.models import Mention


class SourceAdapter(Protocol):
    name: str

    async def search(self, tag: str, limit: int) -> list[Mention]: ...
