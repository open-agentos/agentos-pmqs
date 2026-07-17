"""Settings renders inside the app shell (#90).

Before this, render_settings() built its own standalone <!doctype html> with a
hardcoded palette and no rail -- the only page in the product that wasn't the product.
These tests pin the shell, the sentinel splice, and the token-only styling, none of
which any existing test covered.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import re

from pmqs import products, settings
from pmqs.api.app import app
from pmqs.db import Base, get_session
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


def test_settings_renders_inside_the_shell(db):
    html = render_settings(db)
    assert '<div id="rail">' in html          # left rail present
    assert 'id="view-settings"' in html       # it's a view, not a document
    assert 'id="product-switcher"' in html    # switcher present
    assert "showView('settings')" in html     # and it's the active one


def test_settings_view_sits_in_the_same_document_as_the_other_views(db):
    html = render_settings(db)
    for view in ("view-inbox", "view-workspace", "view-outcomes"):
        assert f'id="{view}"' in html


def test_fixture_sections_are_replaced_by_real_ones(db):
    html = render_settings(db)
    assert "Fixture content" not in html
    for heading in (">You</h2>", ">News</h2>", ">Advanced</h2>"):
        assert heading in html


def test_no_bespoke_palette(db):
    """The old standalone page hardcoded its own hex values. Everything is a token now."""
    html = render_settings(db)
    body = html.split('<!-- SETTINGS SECTIONS -->')[1].split('<!-- /SETTINGS SECTIONS -->')[0]
    assert re.search(r"#[0-9a-fA-F]{3}\b", body) is None  # no hex literals in the spliced markup


def test_advanced_section_shows_the_context_budget(db):
    settings.set_context_budget(db, 1234)
    html = render_settings(db)
    assert 'name="char_budget"' in html
    assert "1234" in html


def test_raw_keys_never_rendered(db):
    settings.set_llm(db, provider="anthropic", model="m", api_key_raw="sk-llm-secret")
    settings.set_news_config(db, api_key_raw="brave-secret", queries=["x"])
    html = render_settings(db)
    assert "sk-llm-secret" not in html
    assert "brave-secret" not in html


def test_missing_sentinel_raises_rather_than_rendering_fixtures(db, tmp_path):
    """A silent fixture render is the failure mode TEMPLATE-CONTRACT.md warns about."""
    bad = tmp_path / "app.html"
    bad.write_text("<html><body>no sentinels here</body></html>")
    with pytest.raises(RuntimeError):
        render_settings(db, template_path=bad)


def test_settings_page_route(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert 'id="view-settings"' in r.text


def test_workspace_prefixed_settings_keeps_you_in_the_workspace(client):
    s = client._session_factory()
    p = products.get_or_create_product(s, org="open-agentos", repo="agentos-pmqs")
    slug = p.slug
    s.close()

    r = client.get(f"/w/{slug}/settings")
    assert r.status_code == 200
    # The slug scopes nothing, but the rail's links stay inside the product.
    assert f"'/w/{slug}/outcomes'" in r.text


def test_unknown_workspace_slug_404s(client):
    r = client.get("/w/nope/settings")
    assert r.status_code == 404


def test_advanced_save_round_trips(client):
    r = client.post("/settings/advanced", data={"char_budget": "2500"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/settings"
    s = client._session_factory()
    assert settings.get_context_budget(s) == 2500
    s.close()


def test_advanced_save_ignores_junk_rather_than_zeroing_the_feed(client):
    client.post("/settings/advanced", data={"char_budget": "2500"})
    client.post("/settings/advanced", data={"char_budget": "banana"})
    s = client._session_factory()
    assert settings.get_context_budget(s) == 2500
    s.close()


def test_prefixed_save_redirects_back_to_the_prefixed_settings(client):
    s = client._session_factory()
    slug = products.get_or_create_product(s, org="open-agentos", repo="agentos-pmqs").slug
    s.close()
    r = client.post(
        f"/w/{slug}/settings",
        data={"provider": "anthropic", "model": "m"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/w/{slug}/settings"
