import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, settings
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
    settings.set_news_config(db, queries=[])
    assert ingest(db) == []


def test_ingest_no_key_returns_empty(db, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", "/nonexistent")
    settings.set_news_config(db, queries=["x"], api_key_ref="BRAVE_API_KEY")
    assert ingest(db) == []


def test_ingest_persists_and_dedups(db, monkeypatch):
    # Stub the network layer to return fixture-parsed items twice; dedup should hold.
    data = json.loads(FIXTURE.read_text())
    parsed = parse_brave_results(data, query="AI agents")
    import pmqs.news.fetch as fetch
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, count=10: parsed)
    settings.set_news_config(db, queries=["AI agents"], api_key_raw="RAWKEY")

    created1 = ingest(db)
    assert len(created1) == 2         # 2 valid items
    created2 = ingest(db)             # same URLs again
    assert len(created2) == 0         # all deduped
    assert len(repository.list_news_items(db)) == 2
