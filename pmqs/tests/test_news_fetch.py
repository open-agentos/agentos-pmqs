import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import products, repository, settings
from pmqs.news.fetch import parse_brave_results, ingest

FIXTURE = Path(__file__).parent / "fixtures" / "brave_news.json"


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_parser_extracts_items_and_skips_urlless():
    data = json.loads(FIXTURE.read_text())
    items = parse_brave_results(data, query="AI agents")
    # 3 results, one has no url → 2 parsed
    assert len(items) == 2
    first = items[0]
    assert first["url"].startswith("https://")
    assert first["title"]
    assert first["source_label"] == "vanityfair.com"
    assert first["published_at"] == "2026-07-14T23:01:39"


def test_ingest_no_queries_returns_empty(db):
    settings.set_news_config(db)
    products.set_news_config(db, products.get_or_create_default_product(db), queries=[])
    assert ingest(db) == []


def test_ingest_no_key_returns_empty(db, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", "/nonexistent")
    settings.set_news_config(db, api_key_ref="BRAVE_API_KEY")
    products.set_news_config(db, products.get_or_create_default_product(db), queries=["x"])
    assert ingest(db) == []


def test_ingest_persists_and_dedups(db, monkeypatch):
    # Stub the network layer to return fixture-parsed items twice; dedup should hold.
    data = json.loads(FIXTURE.read_text())
    parsed = parse_brave_results(data, query="AI agents")
    import pmqs.news.fetch as fetch
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, **kw: parsed)
    settings.set_news_config(db, api_key_raw="RAWKEY")
    products.set_news_config(db, products.get_or_create_default_product(db), queries=["AI agents"])

    created1 = ingest(db)
    assert len(created1) == 2         # 2 valid items
    created2 = ingest(db)             # same URLs again
    assert len(created2) == 0         # all deduped
    assert len(repository.list_news_items(db)) == 2


def test_ingest_fetches_each_products_own_watchlist(db, monkeypatch):
    """The point of #96: before this, one global watchlist fed every product."""
    import pmqs.news.fetch as fetch

    a = products.get_or_create_product(db, org="o", repo="a")
    b = products.get_or_create_product(db, org="o", repo="b")
    products.set_news_config(db, a, watchlist={"companies": ["Anthropic"]})
    products.set_news_config(db, b, watchlist={"companies": ["Figma"]})
    settings.set_news_config(db, api_key_raw="k")

    seen = []
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, **kw: seen.append(q) or [])
    ingest(db)
    assert sorted(seen) == ["Anthropic", "Figma"]


def test_ingest_stamps_the_product_on_every_item(db, monkeypatch):
    import pmqs.news.fetch as fetch

    a = products.get_or_create_product(db, org="o", repo="a")
    products.set_news_config(db, a, watchlist={"companies": ["Anthropic"]})
    settings.set_news_config(db, api_key_raw="k")
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, **kw: [
        {"url": "http://x/1", "title": "t", "source_label": "s", "summary": "", "published_at": None}])

    created = ingest(db)
    assert [i.product_id for i in created] == [a.id]


def test_a_product_with_no_watchlist_is_skipped(db, monkeypatch):
    import pmqs.news.fetch as fetch

    products.get_or_create_product(db, org="o", repo="quiet")
    settings.set_news_config(db, api_key_raw="k")
    seen = []
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, **kw: seen.append(q) or [])
    assert ingest(db) == []
    assert seen == []
