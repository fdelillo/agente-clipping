"""Tests de normalización y determinismo del adapter mock_instagram.

El test de video_view_count usa RawInstagramPost construido a mano (en vez
de confiar en que la generación aleatoria toque ambos casos) para no
depender de qué tipo de post le tocó a cada semilla.
"""

from datetime import datetime, timezone

from app.models import RawInstagramPost
from app.sources.mock_instagram import MockInstagramAdapter


def _sample_raw(**overrides) -> RawInstagramPost:
    defaults = dict(
        id="123456789",
        short_code="ABC123xyz01",
        caption="Una prueba de #tag",
        timestamp=datetime(2026, 8, 30, tzinfo=timezone.utc),
        owner_username="usuario.test",
        likes_count=100,
        comments_count=10,
        video_view_count=None,
        type="Image",
        url="https://www.instagram.com/p/ABC123xyz01/",
    )
    defaults.update(overrides)
    return RawInstagramPost(**defaults)


async def test_normaliza_todos_los_campos():
    adapter = MockInstagramAdapter()
    raw = _sample_raw()
    mention = adapter._normalize(raw, "tag")

    assert mention.provider == "mock_instagram"
    assert mention.external_id == raw.id
    assert mention.tag == "tag"
    assert mention.copy_text == raw.caption
    assert mention.author_handle == raw.owner_username
    assert mention.permalink == raw.url
    assert mention.published_at == raw.timestamp
    assert mention.published_at.tzinfo is not None
    assert mention.metrics["likes"] == raw.likes_count
    assert mention.metrics["comments"] == raw.comments_count
    assert mention.metrics["media_type"] == raw.type


async def test_views_none_si_no_es_video():
    adapter = MockInstagramAdapter()
    raw = _sample_raw(type="Image", video_view_count=None)
    mention = adapter._normalize(raw, "tag")
    assert mention.metrics["views"] is None


async def test_views_presente_si_es_video():
    adapter = MockInstagramAdapter()
    raw = _sample_raw(type="Video", video_view_count=5000)
    mention = adapter._normalize(raw, "tag")
    assert mention.metrics["views"] == 5000


async def test_limit_se_respeta():
    adapter = MockInstagramAdapter()
    mentions = await adapter.search("nike", 4)
    assert len(mentions) == 4


async def test_determinismo_mismo_tag_misma_secuencia():
    adapter = MockInstagramAdapter()
    first = await adapter.search("nike", 5)
    second = await adapter.search("nike", 5)
    assert [m.external_id for m in first] == [m.external_id for m in second]


async def test_determinismo_tags_distintos_dan_ids_distintos():
    adapter = MockInstagramAdapter()
    nike = await adapter.search("nike", 5)
    adidas = await adapter.search("adidas", 5)
    ids_nike = {m.external_id for m in nike}
    ids_adidas = {m.external_id for m in adidas}
    assert ids_nike.isdisjoint(ids_adidas)


async def test_aumentar_limit_conserva_el_prefijo():
    adapter = MockInstagramAdapter()
    small = await adapter.search("nike", 3)
    big = await adapter.search("nike", 6)
    assert [m.external_id for m in big[:3]] == [m.external_id for m in small]
