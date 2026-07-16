"""Tests for the Product switcher UI (issue #55)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs.web.render import render_inbox


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


def _make_workspace(client, org, repo, nickname=None):
    db = client._session_factory()
    product = products.get_or_create_product(db, org=org, repo=repo)
    ws = products.create_workspace(db, product=product, nickname=nickname)
    db.close()
    return ws


def test_switcher_lists_every_workspace_and_marks_current(client):
    ws_a = _make_workspace(client, "acme", "widgets", nickname="Widgets")
    ws_b = _make_workspace(client, "acme", "gizmos", nickname="Gizmos")

    page = client.get(f"/w/{ws_b.slug}/").text
    assert f'href="/w/{ws_a.slug}/">Widgets</a>' in page
    assert f'href="/w/{ws_b.slug}/">Gizmos</a>' in page
    # Current workspace's item carries the "current" class; the other doesn't.
    assert f'class="ps-item current" href="/w/{ws_b.slug}/"' in page
    assert f'class="ps-item" href="/w/{ws_a.slug}/"' in page


def test_switcher_current_name_reflects_active_workspace(client):
    ws_a = _make_workspace(client, "acme", "widgets", nickname="Widgets")
    _make_workspace(client, "acme", "gizmos", nickname="Gizmos")

    page = client.get(f"/w/{ws_a.slug}/").text
    assert 'id="ps-current"' in page
    assert "Widgets" in page.split('id="ps-current"')[1][:200]


def test_switcher_has_add_product_form(client):
    _make_workspace(client, "acme", "widgets")
    page = client.get("/").text
    assert '<form class="ps-add-form" method="post" action="/products"' in page
    assert 'name="repo"' in page


def test_legacy_view_shows_switcher_scoped_to_default_workspace(client):
    # No slug in the URL at all -- render_inbox is still called with db= so the
    # switcher renders, just anchored on the account's default (oldest) workspace.
    ws_default = _make_workspace(client, "open-agentos", "agentos-pmqs")
    _make_workspace(client, "open-agentos", "agentos")

    page = client.get("/").text
    assert 'id="product-switcher"' in page
    assert f'class="ps-item current" href="/w/{ws_default.slug}/"' in page


def test_render_inbox_without_db_falls_back_to_static_fixture(monkeypatch):
    # render_inbox is still callable the old way (db=None) without crashing -- degrades
    # to the static switcher fixture rather than raising.
    html_out = render_inbox([])
    assert "<html" in html_out.lower()


def test_switcher_has_inert_portfolio_placeholder(client):
    _make_workspace(client, "acme", "widgets")
    page = client.get("/").text
    assert 'class="ps-item ps-portfolio"' in page
    assert ">Portfolio<" in page
    # Inert: a plain div, not a link -- nothing to click through to yet.
    portfolio_snippet = page.split('class="ps-item ps-portfolio"')[1][:120]
    assert "href=" not in portfolio_snippet
