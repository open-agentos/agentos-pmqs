"""The News watchlist and the completed News section (#92).

build_queries is pure by design -- no DB, no network, no LLM -- so every composition
case is tested offline here.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import settings
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs.news import fetch
from pmqs.news.watchlist import MAX_QUERIES, build_queries, parse_field
from pmqs.web.render import render_settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        c._session_factory = TestingSession
        yield c
    app.dependency_overrides.clear()


# --- parse_field ---

def test_parse_field_strips_blanks_and_dedups_case_insensitively():
    assert parse_field("  OpenAI \n\n openai \n Anthropic \n") == ["OpenAI", "Anthropic"]


def test_parse_field_keeps_the_case_the_pm_typed():
    assert parse_field("Claude Code") == ["Claude Code"]


def test_parse_field_of_nothing_is_empty():
    assert parse_field("") == []
    assert parse_field(None) == []


# --- build_queries ---

def test_each_term_field_becomes_a_query():
    q = build_queries({"industry": ["ai"], "keywords": ["agents"],
                       "companies": ["Anthropic"], "products": ["Claude"]})
    assert q == ["ai", "agents", "Anthropic", "Claude"]


def test_multi_word_terms_are_quoted_as_phrases():
    assert build_queries({"keywords": ["agent orchestration"]}) == ['"agent orchestration"']


def test_terms_are_deduped_across_fields():
    """First field wins, in TERM_FIELDS order — not dict insertion order."""
    q = build_queries({"companies": ["anthropic"], "keywords": ["Anthropic"]})
    assert q == ["Anthropic"]


def test_sources_restrict_every_query_rather_than_becoming_queries():
    q = build_queries({"keywords": ["agents"], "sources": ["techcrunch.com", "theverge.com"]})
    assert q == ["agents (site:techcrunch.com OR site:theverge.com)"]


def test_one_source_needs_no_or_group():
    assert build_queries({"keywords": ["agents"], "sources": ["techcrunch.com"]}) == [
        "agents site:techcrunch.com"]


def test_sources_alone_produce_nothing():
    """'techcrunch.com' as a search term returns nothing useful."""
    assert build_queries({"sources": ["techcrunch.com"]}) == []


def test_sources_do_not_multiply_the_query_count():
    q = build_queries({"keywords": ["a", "b"], "sources": ["x.com", "y.com", "z.com"]})
    assert len(q) == 2  # not 2 x 3


def test_raw_queries_pass_through_untouched_after_the_composed_ones():
    q = build_queries({"keywords": ["agents"]}, ["site:news.ycombinator.com claude"])
    assert q == ["agents", "site:news.ycombinator.com claude"]


def test_query_count_is_capped():
    q = build_queries({"keywords": [f"k{i}" for i in range(100)]})
    assert len(q) == MAX_QUERIES


def test_empty_watchlist_is_empty_not_an_error():
    assert build_queries({}) == []


# --- config ---

def test_news_config_defaults_are_additive_and_safe(db):
    cfg = settings.get_news_config(db)
    assert cfg["enabled"] is True
    assert cfg["count"] == 10
    assert cfg["freshness"] == "pw"
    assert cfg["watchlist"] == {}
    assert cfg["last_run"] == ""


def test_effective_queries_compose_watchlist_plus_raw(db):
    settings.set_news_config(db, watchlist={"keywords": ["agents"]}, queries=["raw one"])
    assert settings.effective_news_queries(db) == ["agents", "raw one"]


def test_saving_the_watchlist_does_not_blank_the_last_run_stamp(db):
    settings.record_news_run(db, promoted=4)
    stamped = settings.get_news_config(db)["last_run"]
    settings.set_news_config(db, watchlist={"keywords": ["agents"]})
    cfg = settings.get_news_config(db)
    assert cfg["last_run"] == stamped
    assert cfg["last_promoted"] == 4


def test_record_news_run_stamps(db):
    settings.record_news_run(db, promoted=2)
    cfg = settings.get_news_config(db)
    assert cfg["last_run"]
    assert cfg["last_promoted"] == 2


# --- fetch ---

def test_disabled_means_no_fetch(db, monkeypatch):
    called = []
    monkeypatch.setattr(fetch, "_fetch_query", lambda *a, **k: called.append(1) or [])
    settings.set_news_config(db, enabled=False, watchlist={"keywords": ["agents"]},
                            api_key_raw="k")
    assert fetch.ingest(db) == []
    assert called == []


def test_count_and_freshness_reach_the_fetcher(db, monkeypatch):
    seen = {}

    def _spy(q, k, count=10, freshness=""):
        seen.update(query=q, count=count, freshness=freshness)
        return []

    monkeypatch.setattr(fetch, "_fetch_query", _spy)
    settings.set_news_config(db, watchlist={"keywords": ["agents"]}, api_key_raw="k",
                             count=25, freshness="pd")
    fetch.ingest(db)
    assert seen == {"query": "agents", "count": 25, "freshness": "pd"}


def test_ingest_searches_the_watchlist_not_just_the_raw_queries(db, monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, **kw: seen.append(q) or [])
    settings.set_news_config(db, watchlist={"companies": ["Anthropic"]}, api_key_raw="k")
    fetch.ingest(db)
    assert seen == ["Anthropic"]


# --- render ---

def test_watchlist_fields_render(db):
    html = render_settings(db)
    for field in ("wl_industry", "wl_keywords", "wl_companies", "wl_products", "wl_sources"):
        assert f'name="{field}"' in html
    assert 'name="freshness"' in html
    assert 'name="count"' in html
    assert 'name="news_enabled"' in html


def test_status_line_reports_the_key_as_a_boolean_only(db, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    settings.set_news_config(db, api_key_raw="brave-secret-value",
                             watchlist={"keywords": ["agents"]})
    html = render_settings(db)
    assert "resolves" in html
    assert "brave-secret" not in html
    assert "brave-secret-value"[:4] not in html.split("<!-- SETTINGS SECTIONS -->")[1]


def test_status_line_says_never_before_the_first_run(db):
    assert ">never<" in render_settings(db)


def test_composed_queries_are_previewed(db):
    settings.set_news_config(db, watchlist={"keywords": ["agent orchestration"],
                                            "sources": ["techcrunch.com"]})
    html = render_settings(db)
    assert "&quot;agent orchestration&quot; site:techcrunch.com" in html


# --- routes ---

def test_watchlist_round_trips_through_the_form(client):
    r = client.post("/settings/news", data={
        "news_enabled": "1",
        "news_api_key_ref": "BRAVE_API_KEY",
        "wl_industry": "agent orchestration",
        "wl_companies": "Anthropic\nOpenAI",
        "wl_sources": "techcrunch.com",
        "count": "15", "freshness": "pd", "top_n": "5", "min_relevance": "0.7",
    }, follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    cfg = settings.get_news_config(s)
    assert cfg["watchlist"]["companies"] == ["Anthropic", "OpenAI"]
    assert cfg["watchlist"]["sources"] == ["techcrunch.com"]
    assert cfg["count"] == 15 and cfg["freshness"] == "pd"
    assert settings.effective_news_queries(s) == ['"agent orchestration" site:techcrunch.com',
                                                  "Anthropic site:techcrunch.com",
                                                  "OpenAI site:techcrunch.com"]
    s.close()


def test_unchecked_checkbox_means_off(client):
    client.post("/settings/news", data={"news_enabled": "1"})
    client.post("/settings/news", data={})  # checkbox posts nothing when unchecked
    s = client._session_factory()
    assert settings.get_news_config(s)["enabled"] is False
    s.close()


def test_junk_numbers_keep_the_current_value(client):
    client.post("/settings/news", data={"count": "15"})
    client.post("/settings/news", data={"count": "banana"})
    s = client._session_factory()
    assert settings.get_news_config(s)["count"] == 15
    s.close()


def test_fetch_now_returns_to_settings(client):
    r = client.post("/news/ingest", data={"return_to": "/settings"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?news=none"


def test_fetch_now_still_defaults_to_the_inbox(client):
    r = client.post("/news/ingest", follow_redirects=False)
    assert r.headers["location"] == "/?news=none"


def test_offsite_return_to_is_refused(client):
    r = client.post("/news/ingest", data={"return_to": "//evil.example.com"},
                    follow_redirects=False)
    assert r.headers["location"] == "/?news=none"


def test_fetch_now_stamps_the_run_even_when_nothing_is_promoted(client):
    client.post("/news/ingest", data={"return_to": "/settings"})
    s = client._session_factory()
    assert settings.get_news_config(s)["last_run"]
    s.close()
