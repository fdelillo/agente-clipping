"""Adapter mock para X: genera datos con la forma cruda real de la API v2 de
X, para que normalizarlos a `Mention` sea trabajo honesto (ver docstring de
app/models.py).

Separamos explícitamente dos responsabilidades:

- `_fetch_raw`: simula la llamada a la fuente y devuelve objetos crudos
  (`RawXPost`), sin tocar el esquema común.
- `_normalize`: mapea un objeto crudo a `Mention`.

Esa separación es la que permite, en la Etapa 5, reemplazar solo
`_fetch_raw` por una llamada HTTP real a Apify (que además va a devolver
JSON parseable directo a `RawXPost`) dejando `_normalize` intacto: la lógica
de mapeo no le importa de dónde salió el crudo.
"""

import random
from datetime import timedelta

from app.models import Mention, RawXAuthor, RawXMetrics, RawXPost
from app.sources._fake import FIRST_NAMES, seed_for, today_utc_midnight

# Mezcla de tono a propósito: la Etapa 2 (análisis con LLM) necesita copies
# variados para tener algo real que clasificar, no solo texto positivo.
_POSITIVE_TEMPLATES = [
    "Buenísimo lo de {tag}, no me lo esperaba tan bien 🙌",
    "{tag} viene remando bien últimamente, para destacar de verdad.",
    "Nada que decir, {tag} cumplió y de sobra esta vez.",
    "Me sorprendió {tag}, mucho mejor de lo que pensaba.",
    "Como fan de siempre, {tag} me tiene reconciliado otra vez.",
]
_NEGATIVE_TEMPLATES = [
    "La verdad que con {tag} me quedé con las ganas, esperaba mucho más.",
    "{tag} bajó un montón, ya no es lo mismo que antes.",
    "Otra vez la misma con {tag}, la verdad que cansa.",
    "No entiendo la decisión de {tag}, para mí un desastre.",
    "Bastante flojo lo de {tag} hoy, se puede hacer mejor.",
]
_NEUTRAL_TEMPLATES = [
    "¿Alguien vio las noticias de {tag}? Quiero opiniones.",
    "{tag} salió en todos lados hoy, raro.",
    "Sigo de cerca lo de {tag}, veremos cómo sigue esto.",
    "¿Alguien sabe algo más de {tag}? Ni idea de qué pensar todavía.",
    "Leyendo sobre {tag} en este momento, después cuento.",
]
_TEMPLATES_BY_SENTIMENT = {
    "positive": _POSITIVE_TEMPLATES,
    "negative": _NEGATIVE_TEMPLATES,
    "neutral": _NEUTRAL_TEMPLATES,
}


class MockXAdapter:
    name = "mock_x"

    async def search(self, tag: str, limit: int) -> list[Mention]:
        raw_posts = self._fetch_raw(tag, limit)
        return [self._normalize(raw, tag) for raw in raw_posts]

    def _fetch_raw(self, tag: str, limit: int) -> list[RawXPost]:
        # Un único Random sembrado por (provider, tag) y consumido en orden
        # secuencial, item tras item. Esto es lo que garantiza que subir
        # `limit` solo agrega elementos nuevos al final: los primeros N
        # items ya consumieron exactamente la misma secuencia de números
        # pseudo-aleatorios sin importar cuántos se pidan después.
        rng = random.Random(seed_for(self.name, tag))
        reference = today_utc_midnight()

        posts = []
        for _ in range(limit):
            sentiment = rng.choice(("positive", "negative", "neutral"))
            template = rng.choice(_TEMPLATES_BY_SENTIMENT[sentiment])
            text = template.format(tag=tag)

            first_name = rng.choice(FIRST_NAMES)
            suffix = rng.randint(100, 99999)
            username = f"{first_name}{suffix}"
            user_id = str(rng.randint(10**9, 10**10 - 1))
            tweet_id = str(rng.randint(10**17, 10**18 - 1))

            offset_seconds = rng.uniform(0, 7 * 24 * 3600)
            created_at = reference - timedelta(seconds=offset_seconds)

            metrics = RawXMetrics(
                retweet_count=rng.randint(0, 500),
                reply_count=rng.randint(0, 200),
                like_count=rng.randint(0, 5000),
                quote_count=rng.randint(0, 100),
                impression_count=rng.randint(100, 50000),
            )
            posts.append(
                RawXPost(
                    id=tweet_id,
                    text=text,
                    created_at=created_at,
                    lang="es",
                    author=RawXAuthor(id=user_id, username=username, name=first_name.capitalize()),
                    public_metrics=metrics,
                )
            )
        return posts

    def _normalize(self, raw: RawXPost, tag: str) -> Mention:
        return Mention(
            provider=self.name,
            external_id=raw.id,
            tag=tag,
            author_handle=raw.author.username,
            copy_text=raw.text,
            permalink=f"https://x.com/{raw.author.username}/status/{raw.id}",
            published_at=raw.created_at,
            # Claves unificadas con mock_instagram donde el concepto es el
            # mismo ("likes" en ambas) para que el informe de la Etapa 4
            # pueda comparar X vs. IG sin tener que traducir nombres de
            # campo primero. Lo que no tiene equivalente en la otra red
            # (retweets, quotes) queda con el nombre propio de X.
            metrics={
                "retweets": raw.public_metrics.retweet_count,
                "replies": raw.public_metrics.reply_count,
                "likes": raw.public_metrics.like_count,
                "quotes": raw.public_metrics.quote_count,
                "views": raw.public_metrics.impression_count,
            },
        )


adapter = MockXAdapter()
