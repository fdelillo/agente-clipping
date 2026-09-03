"""Adapter mock para Instagram: genera datos con la forma cruda real del
scraper de Apify para Instagram, para que normalizarlos a `Mention` sea
trabajo honesto (ver docstring de app/models.py).

Misma separación de responsabilidades que mock_x.py y el mismo motivo: en
la Etapa 5, cambiar `_fetch_raw` por la llamada real a Apify no debería
tocar `_normalize`.
"""

import random
import string
from datetime import timedelta

from app.models import Mention, RawInstagramPost
from app.sources._fake import FIRST_NAMES, seed_for, today_utc_midnight

# Estilo más "caption" que el de X: más largo, con emojis y hashtag, que es
# como se escribe realmente en Instagram. Mezcla de tono a propósito, misma
# razón que en mock_x.py: la Etapa 2 necesita variedad real para clasificar.
_POSITIVE_TEMPLATES = [
    "Un golazo esto de {tag} 😍 no lo puedo creer #{tag}",
    "{tag} superó todas mis expectativas ✨ recomendadísimo total",
    "Hoy fue un día hermoso gracias a {tag} 💛 #{tag}",
    "Directo al corazón esto de {tag} 🙌 se las recomiendo a todos",
]
_NEGATIVE_TEMPLATES = [
    "La verdad que {tag} me dejó bastante fría, esperaba otra cosa 😕",
    "No puedo creer lo que pasó con {tag}, una decepción total #{tag}",
    "{tag} bajó muchísimo el nivel últimamente, se nota un montón",
    "Sinceramente esperaba más de {tag}, no lo recomiendo",
]
_NEUTRAL_TEMPLATES = [
    "Nueva publicación sobre {tag}, cuéntenme qué opinan 👇",
    "{tag} en el timeline de hoy, atentos a lo que viene",
    "Compartiendo esto de {tag} porque me pareció interesante #{tag}",
    "¿Vieron lo de {tag}? Todavía no sé qué pensar",
]
_TEMPLATES_BY_SENTIMENT = {
    "positive": _POSITIVE_TEMPLATES,
    "negative": _NEGATIVE_TEMPLATES,
    "neutral": _NEUTRAL_TEMPLATES,
}

_POST_TYPES = ("Video", "Image", "Sidecar")

_SHORTCODE_ALPHABET = string.ascii_letters + string.digits


class MockInstagramAdapter:
    name = "mock_instagram"

    async def search(self, tag: str, limit: int) -> list[Mention]:
        raw_posts = self._fetch_raw(tag, limit)
        return [self._normalize(raw, tag) for raw in raw_posts]

    def _fetch_raw(self, tag: str, limit: int) -> list[RawInstagramPost]:
        # Mismo esquema que mock_x: un solo Random sembrado por
        # (provider, tag), consumido secuencialmente. Subir `limit` solo
        # agrega posts al final sin alterar los ya generados.
        rng = random.Random(seed_for(self.name, tag))
        reference = today_utc_midnight()

        posts = []
        for _ in range(limit):
            sentiment = rng.choice(("positive", "negative", "neutral"))
            template = rng.choice(_TEMPLATES_BY_SENTIMENT[sentiment])
            caption = template.format(tag=tag)

            first_name = rng.choice(FIRST_NAMES)
            suffix = rng.randint(100, 99999)
            username = f"{first_name}.{suffix}"

            media_id = str(rng.randint(10**17, 10**18 - 1))
            short_code = "".join(rng.choices(_SHORTCODE_ALPHABET, k=11))

            post_type = rng.choice(_POST_TYPES)
            likes = rng.randint(0, 10000)
            comments = rng.randint(0, 500)
            # None si no es video: Instagram no reporta reproducciones para
            # posts de imagen o carrusel (Sidecar).
            video_views = rng.randint(100, 100000) if post_type == "Video" else None

            offset_seconds = rng.uniform(0, 7 * 24 * 3600)
            timestamp = reference - timedelta(seconds=offset_seconds)

            posts.append(
                RawInstagramPost(
                    id=media_id,
                    short_code=short_code,
                    caption=caption,
                    timestamp=timestamp,
                    owner_username=username,
                    likes_count=likes,
                    comments_count=comments,
                    video_view_count=video_views,
                    type=post_type,
                    url=f"https://www.instagram.com/p/{short_code}/",
                )
            )
        return posts

    def _normalize(self, raw: RawInstagramPost, tag: str) -> Mention:
        return Mention(
            provider=self.name,
            external_id=raw.id,
            tag=tag,
            author_handle=raw.owner_username,
            copy_text=raw.caption,
            permalink=raw.url,
            published_at=raw.timestamp,
            # "likes" con el mismo nombre que en mock_x.py a propósito: es
            # el mismo concepto en ambas redes y el informe de la Etapa 4
            # va a comparar X vs. IG. "comments" e "media_type" no tienen
            # equivalente unificado y quedan con el nombre propio de IG.
            metrics={
                "likes": raw.likes_count,
                "comments": raw.comments_count,
                "views": raw.video_view_count,
                "media_type": raw.type,
            },
        )


adapter = MockInstagramAdapter()
