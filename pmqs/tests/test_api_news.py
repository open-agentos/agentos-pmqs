"""API tests for news ingest + settings. LLM + network stubbed; no real calls."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs import products, repository, settings


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
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


def test_save_news_settings(client):
    # In a real deployment init_db always backfills a default product; the test DBs
    # skip the backfills, so create one -- there's nothing to hang a watchlist on
    # otherwise (#96).
    s0 = client._session_factory()
    slug = products.get_or_create_default_product(s0).slug
    s0.close()
    # Two surfaces as of #98: the throttles are the account's...
    r = client.post("/settings/news", data={
        "news_api_key_ref": "BRAVE_API_KEY", "top_n": "3", "min_relevance": "0.6",
    }, follow_redirects=False)
    assert r.status_code == 303
    # ...the watchlist is the product's.
    r = client.post(f"/w/{slug}/settings", data={
        "news_queries": "agent orchestration\nAI PM tools",
        "product_profile": "PMQs on AgentOS",
    }, follow_redirects=False)
    assert r.status_code == 303

    db = client._session_factory()
    assert products.get_news_config(db, products.list_products(db)[0])["queries"] == [
        "agent orchestration", "AI PM tools"]
    assert settings.get_news_config(db)["min_relevance"] == 0.6
    db.close()


def test_news_ingest_route_is_gone(client):
    # Fetching moved onto the Inbox Refresh; the standalone Settings endpoint is retired.
    r = client.post("/news/ingest", follow_redirects=False)
    assert r.status_code == 404


def test_settings_page_shows_news_section_without_a_fetch_button(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert ">News</h2>" in r.text          # the News settings (key/throttles) stay
    assert "Fetch news now" not in r.text  # the button moved to the Inbox Refresh
    assert "Refresh" in r.text             # status line points at where fetching lives now
