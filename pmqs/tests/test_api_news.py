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
from pmqs import repository, settings


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
    r = client.post("/settings/news", data={
        "news_api_key_ref": "BRAVE_API_KEY",
        "news_queries": "agent orchestration\nAI PM tools",
        "product_profile": "PMQs on AgentOS",
        "top_n": "3", "min_relevance": "0.6",
    }, follow_redirects=False)
    assert r.status_code == 303
    db = client._session_factory()
    cfg = settings.get_news_config(db)
    assert cfg["queries"] == ["agent orchestration", "AI PM tools"]
    assert cfg["min_relevance"] == 0.6
    db.close()


def test_ingest_no_config_redirects_with_none(client):
    # No queries/key configured → ingest promotes nothing → ?news=none
    r = client.post("/news/ingest", follow_redirects=False)
    assert r.status_code == 303
    assert "news=none" in r.headers["location"]


def test_settings_page_shows_news_section(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert ">News</h2>" in r.text
    assert "Fetch news now" in r.text
