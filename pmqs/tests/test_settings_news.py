from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_news_defaults(db):
    cfg = settings.get_news_config(db)
    assert cfg["api_key_ref"] == "BRAVE_API_KEY"
    assert cfg["top_n"] == 3
    assert 0.0 <= cfg["min_relevance"] <= 1.0
    assert cfg["queries"] == []


def test_set_and_get_news_config(db):
    settings.set_news_config(
        db, queries=["agent orchestration", "AI PM tools"],
        product_profile="PMQs: PM intelligence on AgentOS", top_n=5, min_relevance=0.7,
    )
    cfg = settings.get_news_config(db)
    assert cfg["queries"] == ["agent orchestration", "AI PM tools"]
    assert cfg["top_n"] == 5
    assert cfg["min_relevance"] == 0.7
    assert "PMQs" in cfg["product_profile"]


def test_resolve_brave_key_prefers_raw(db):
    settings.set_news_config(db, api_key_raw="RAWKEY123", queries=["x"])
    assert settings.resolve_brave_key(db) == "RAWKEY123"


def test_resolve_brave_key_from_env(db, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "ENVKEY456")
    settings.set_news_config(db, api_key_ref="BRAVE_API_KEY", queries=["x"])
    assert settings.resolve_brave_key(db) == "ENVKEY456"


def test_resolve_brave_key_empty_when_none(db, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", "/nonexistent-hermes-home")
    settings.set_news_config(db, api_key_ref="BRAVE_API_KEY", queries=["x"])
    assert settings.resolve_brave_key(db) == ""
