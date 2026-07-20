"""Scope C of docs/build-spec-optional-repo-onramp.md: POST /products no longer requires
a repo. Empty repo creates a website-only product; a malformed one still 400s inline.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products
from pmqs.api.app import app
from pmqs.db import Base, get_session


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _override():
        s = TS()
        try:
            yield s
        finally:
            s.close()

    import pmqs.pipeline as pipeline
    monkeypatch.setattr(pipeline, "seed_workspace", lambda db, product: [])
    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        c._session_factory = TS
        yield c
    app.dependency_overrides.clear()


def test_add_with_no_repo_creates_a_website_only_product(client):
    r = client.post("/products", data={"website": "https://acme.example", "display_name": "Acme"},
                    follow_redirects=False)
    assert r.status_code == 303  # created, not the 400 the old required-repo path gave
    s = client._session_factory()
    p = products.list_products(s)[0]
    assert p.org is None and p.repo is None
    assert p.has_repo is False
    assert r.headers["location"] == f"/w/{p.slug}/settings?added=1"
    s.close()


def test_website_only_create_persists_website_and_watchlist(client):
    client.post("/products", data={
        "website": "https://acme.example",
        "display_name": "Acme",
        "wl_industry": "widgets",
        "product_profile": "The widget platform.",
    }, follow_redirects=False)
    s = client._session_factory()
    p = products.list_products(s)[0]
    cfg = products.get_news_config(s, p)
    assert cfg["website"] == "https://acme.example"
    assert cfg["product_profile"] == "The widget platform."
    assert "widgets" in cfg["watchlist"].get("industry", [])
    s.close()


def test_empty_repo_is_not_a_malformed_repo(client):
    # blank field must sail through, not trip the invalid_repo re-render
    r = client.post("/products", data={"website": "https://acme.example", "repo": "  "},
                    follow_redirects=False)
    assert r.status_code == 303


def test_malformed_repo_still_400s_inline(client):
    r = client.post("/products", data={"repo": "not-a-ref", "display_name": "Typo"},
                    follow_redirects=False)
    assert r.status_code == 400
    assert "repository" in r.text.lower()
    assert 'value="Typo"' in r.text  # reviewed fields preserved


def test_valid_repo_path_unchanged(client):
    r = client.post("/products", data={"repo": "open-agentos/agentos"}, follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    p = products.get_product_by_org_repo(s, "open-agentos", "agentos")
    assert p is not None and p.has_repo
    assert r.headers["location"] == f"/w/{p.slug}/settings?added=1"
    s.close()
