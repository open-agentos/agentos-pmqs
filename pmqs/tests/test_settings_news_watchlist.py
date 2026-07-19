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

from pmqs import products, settings
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs.news import fetch
from pmqs.news.watchlist import MAX_QUERIES, build_queries, parse_field
from pmqs.web.render import render_product_settings, render_settings


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
    assert cfg["last_run"] == ""


def test_effective_queries_compose_watchlist_plus_raw(db):
    p = products.get_or_create_default_product(db)
    products.set_news_config(db, p, watchlist={"keywords": ["agents"]}, queries=["raw one"])
    assert settings.effective_news_queries(db, p) == ["agents", "raw one"]


def test_effective_queries_are_per_product(db):
    """The point of #96: two products, two watchlists, two different runs."""
    a = products.get_or_create_product(db, org="o", repo="a")
    b = products.get_or_create_product(db, org="o", repo="b")
    products.set_news_config(db, a, watchlist={"companies": ["Anthropic"]})
    products.set_news_config(db, b, watchlist={"companies": ["Figma"]})
    assert settings.effective_news_queries(db, a) == ["Anthropic"]
    assert settings.effective_news_queries(db, b) == ["Figma"]


def test_saving_the_watchlist_does_not_blank_the_last_run_stamp(db):
    settings.record_news_run(db, promoted=4)
    stamped = settings.get_news_config(db)["last_run"]
    settings.set_news_config(db, count=12)
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
    settings.set_news_config(db, enabled=False, api_key_raw="k")
    products.set_news_config(db, products.get_or_create_default_product(db),
                             watchlist={"keywords": ["agents"]})
    assert fetch.ingest(db) == []
    assert called == []


def test_count_and_freshness_reach_the_fetcher(db, monkeypatch):
    seen = {}

    def _spy(q, k, count=10, freshness=""):
        seen.update(query=q, count=count, freshness=freshness)
        return []

    monkeypatch.setattr(fetch, "_fetch_query", _spy)
    settings.set_news_config(db, api_key_raw="k", count=25, freshness="pd")
    products.set_news_config(db, products.get_or_create_default_product(db),
                             watchlist={"keywords": ["agents"]})
    fetch.ingest(db)
    assert seen == {"query": "agents", "count": 25, "freshness": "pd"}


def test_ingest_searches_the_watchlist_not_just_the_raw_queries(db, monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "_fetch_query", lambda q, k, **kw: seen.append(q) or [])
    settings.set_news_config(db, api_key_raw="k")
    products.set_news_config(db, products.get_or_create_default_product(db),
                             watchlist={"companies": ["Anthropic"]})
    fetch.ingest(db)
    assert seen == ["Anthropic"]


# --- render ---

def test_watchlist_fields_render_on_the_product_page(db):
    p = products.get_or_create_default_product(db)
    html = render_product_settings(db, p, workspace_slug=p.slug)
    for field in ("wl_industry", "wl_keywords", "wl_companies", "wl_products", "wl_sources"):
        assert f'name="{field}"' in html


def test_throttles_render_on_the_account_page(db):
    html = render_settings(db)
    assert 'name="freshness"' in html
    assert 'name="count"' in html
    assert 'name="news_enabled"' in html


def test_status_line_reports_the_key_as_a_boolean_only(db, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    settings.set_news_config(db, api_key_raw="brave-secret-value")
    products.set_news_config(db, products.get_or_create_default_product(db),
                             watchlist={"keywords": ["agents"]})
    html = render_settings(db)
    assert "resolves" in html
    assert "brave-secret" not in html
    assert "brave-secret-value"[:4] not in html.split("<!-- SETTINGS SECTIONS -->")[1]


def test_status_line_says_never_before_the_first_run(db):
    assert ">never<" in render_settings(db)


def test_composed_queries_are_previewed(db):
    p = products.get_or_create_default_product(db)
    products.set_news_config(db, p, watchlist={"keywords": ["agent orchestration"],
                                               "sources": ["techcrunch.com"]})
    html = render_product_settings(db, p, workspace_slug=p.slug)
    assert "&quot;agent orchestration&quot; site:techcrunch.com" in html


# --- routes ---

def test_watchlist_round_trips_through_the_product_form(client):
    s0 = client._session_factory()
    slug = products.get_or_create_default_product(s0).slug
    s0.close()
    r = client.post(f"/w/{slug}/settings", data={
        "wl_industry": "agent orchestration",
        "wl_companies": "Anthropic\nOpenAI",
        "wl_sources": "techcrunch.com",
    }, follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    cfg = products.get_news_config(s, products.list_products(s)[0])
    assert cfg["watchlist"]["companies"] == ["Anthropic", "OpenAI"]
    assert cfg["watchlist"]["sources"] == ["techcrunch.com"]
    # What the form saved is what ingest() will run -- one composer, no drift.
    assert settings.effective_news_queries(s, products.list_products(s)[0]) == [
        '"agent orchestration" site:techcrunch.com',
        "Anthropic site:techcrunch.com",
        "OpenAI site:techcrunch.com"]
    s.close()


def test_throttles_round_trip_through_the_account_form(client):
    r = client.post("/settings/news", data={
        "news_enabled": "1", "news_api_key_ref": "BRAVE_API_KEY",
        "count": "15", "freshness": "pd", "top_n": "5", "min_relevance": "0.7",
    }, follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    acct = settings.get_news_config(s)
    assert acct["count"] == 15 and acct["freshness"] == "pd" and acct["top_n"] == 5
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

