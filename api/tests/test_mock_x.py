"""Tests de normalización y determinismo del adapter mock_x.

Sin DB real: son tests puros de dominio, sobre el adapter directamente.
"""

from app.sources.mock_x import MockXAdapter


async def test_normaliza_todos_los_campos():
    adapter = MockXAdapter()
    raw = adapter._fetch_raw("milei", 1)[0]
    mention = adapter._normalize(raw, "milei")

    assert mention.provider == "mock_x"
    assert mention.external_id == raw.id
    assert mention.tag == "milei"
    assert mention.author_handle == raw.author.username
    assert mention.copy_text == raw.text
    assert mention.permalink == f"https://x.com/{raw.author.username}/status/{raw.id}"
    assert mention.published_at == raw.created_at
    assert mention.published_at.tzinfo is not None
    assert mention.metrics == {
        "retweets": raw.public_metrics.retweet_count,
        "replies": raw.public_metrics.reply_count,
        "likes": raw.public_metrics.like_count,
        "quotes": raw.public_metrics.quote_count,
        "views": raw.public_metrics.impression_count,
    }


async def test_limit_se_respeta():
    adapter = MockXAdapter()
    mentions = await adapter.search("milei", 7)
    assert len(mentions) == 7


async def test_determinismo_mismo_tag_misma_secuencia():
    adapter = MockXAdapter()
    first = await adapter.search("milei", 5)
    second = await adapter.search("milei", 5)
    assert [m.external_id for m in first] == [m.external_id for m in second]


async def test_determinismo_tags_distintos_dan_ids_distintos():
    adapter = MockXAdapter()
    milei = await adapter.search("milei", 5)
    nike = await adapter.search("nike", 5)
    ids_milei = {m.external_id for m in milei}
    ids_nike = {m.external_id for m in nike}
    assert ids_milei.isdisjoint(ids_nike)


async def test_aumentar_limit_conserva_el_prefijo():
    adapter = MockXAdapter()
    small = await adapter.search("milei", 3)
    big = await adapter.search("milei", 6)
    assert [m.external_id for m in big[:3]] == [m.external_id for m in small]
