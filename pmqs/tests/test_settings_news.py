from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import products, settings


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
    # queries/watchlist/product_profile moved onto Product in #96 and are deliberately
    # absent from the account config -- get_news_config filters to its own keys.
    assert "queries" not in cfg
    assert "product_profile" not in cfg


def test_set_and_get_news_config(db):
    settings.set_news_config(db, top_n=5, min_relevance=0.7, count=20, freshness="pd")
    cfg = settings.get_news_config(db)
    assert cfg["top_n"] == 5
    assert cfg["min_relevance"] == 0.7
    assert cfg["count"] == 20
    assert cfg["freshness"] == "pd"


def test_product_news_config_round_trips(db):
    """The watchlist and profile live on Product as of #96."""
    p = products.get_or_create_default_product(db)
    products.set_news_config(db, p, queries=["agent orchestration", "AI PM tools"],
                             product_profile="PMQs: PM intelligence on AgentOS")
    cfg = products.get_news_config(db, p)
    assert cfg["queries"] == ["agent orchestration", "AI PM tools"]
    assert "PMQs" in cfg["product_profile"]


def test_product_news_config_defaults_when_unset(db):
    assert products.get_news_config(db, products.get_or_create_default_product(db)) == {
        "watchlist": {}, "queries": [], "product_profile": ""}


def test_product_news_config_tolerates_no_product_yet(db):
    """Render paths call this before the first product exists."""
    assert products.get_news_config(db, None)["watchlist"] == {}


def test_resolve_brave_key_prefers_raw(db):
    settings.set_news_config(db, api_key_raw="RAWKEY123")
    assert settings.resolve_brave_key(db) == "RAWKEY123"


def test_resolve_brave_key_from_env(db, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "ENVKEY456")
    settings.set_news_config(db, api_key_ref="BRAVE_API_KEY")
    assert settings.resolve_brave_key(db) == "ENVKEY456"


def test_resolve_brave_key_empty_when_none(db, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", "/nonexistent-hermes-home")
    settings.set_news_config(db, api_key_ref="BRAVE_API_KEY")
    assert settings.resolve_brave_key(db) == ""


def test_legacy_global_watchlist_folds_onto_the_default_product(tmp_path, monkeypatch):
    """#96 moved the watchlist onto Product. A PM who configured one last week should
    not open Settings to find it gone."""
    import json as _json

    from pmqs import db as db_mod
    from pmqs.models import Setting

    monkeypatch.setattr(db_mod, "engine", create_engine(f"sqlite:///{tmp_path}/t.db", future=True))
    monkeypatch.setattr(db_mod, "SessionLocal",
                        sessionmaker(bind=db_mod.engine, expire_on_commit=False, future=True))
    Base.metadata.create_all(db_mod.engine)

    # A pre-#96 settings row: watchlist and profile living on the account.
    with db_mod.SessionLocal() as s:
        s.add(Setting(key="news", value=_json.dumps({
            "api_key_ref": "BRAVE_API_KEY",
            "watchlist": {"companies": ["Anthropic"]},
            "queries": ["raw q"],
            "product_profile": "the old profile",
            "top_n": 5,
        })))
        s.commit()

    db_mod._fold_news_config_onto_default_product()

    with db_mod.SessionLocal() as s:
        p = products.get_or_create_default_product(s)
        cfg = products.get_news_config(s, p)
        assert cfg["watchlist"] == {"companies": ["Anthropic"]}
        assert cfg["queries"] == ["raw q"]
        assert cfg["product_profile"] == "the old profile"
        # Account row keeps its own keys and loses the moved ones.
        acct = _json.loads(s.get(Setting, "news").value)
        assert acct["top_n"] == 5
        assert "watchlist" not in acct and "product_profile" not in acct

    # Idempotent: a second run is a no-op and doesn't clobber the product's config.
    db_mod._fold_news_config_onto_default_product()
    with db_mod.SessionLocal() as s:
        assert products.get_news_config(s, products.get_or_create_default_product(s))["queries"] == ["raw q"]
