"""Tests for product-scoped routing under /w/{workspace_slug}/... (issue #56)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products, repository
from pmqs.api.app import app
from pmqs.db import Base, get_session


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


def _make_product(client, org, repo, nickname=None):
    db = client._session_factory()
    product = products.get_or_create_product(db, org=org, repo=repo, nickname=nickname)
    db.close()
    return product


def test_scoped_inbox_only_shows_that_products_questions(client):
    p_a = _make_product(client, "acme", "widgets")
    p_b = _make_product(client, "acme", "gizmos")

    db = client._session_factory()
    repository.create_question(db, title="Widgets question", source="pm", product_id=p_a.id)
    repository.create_question(db, title="Gizmos question", source="pm", product_id=p_b.id)
    db.close()

    r_a = client.get(f"/w/{p_a.slug}/")
    r_b = client.get(f"/w/{p_b.slug}/")
    assert "Widgets question" in r_a.text
    assert "Gizmos question" not in r_a.text
    assert "Gizmos question" in r_b.text
    assert "Widgets question" not in r_b.text


def test_unknown_workspace_slug_is_404(client):
    r = client.get("/w/does-not-exist/")
    assert r.status_code == 404


def test_scoped_quick_add_lands_in_the_right_product(client):
    p_a = _make_product(client, "acme", "widgets")
    p_b = _make_product(client, "acme", "gizmos")

    r = client.post(f"/w/{p_a.slug}/quick-add", data={"title": "New idea"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/w/{p_a.slug}/"

    db = client._session_factory()
    assert len(repository.list_questions(db, product_id=p_a.id)) == 1
    assert len(repository.list_questions(db, product_id=p_b.id)) == 0
    db.close()


def test_legacy_unprefixed_routes_still_work_unchanged(client):
    # No product slug at all -- pre-#56 behaviour: falls back to whatever product(s)
    # exist, doesn't 404, doesn't require a slug.
    r = client.post("/quick-add", data={"title": "Legacy add"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    r2 = client.get("/")
    assert r2.status_code == 200
    assert "Legacy add" in r2.text


def test_scoped_outcomes_ledger_isolated_per_product(client):
    p_a = _make_product(client, "acme", "widgets")
    p_b = _make_product(client, "acme", "gizmos")

    db = client._session_factory()
    repository.create_outcome(db, type="document", payload={"title": "A doc"}, product_id=p_a.id)
    repository.create_outcome(db, type="document", payload={"title": "B doc"}, product_id=p_b.id)
    db.close()

    r_a = client.get(f"/w/{p_a.slug}/api/outcomes")
    r_b = client.get(f"/w/{p_b.slug}/api/outcomes")
    assert len(r_a.json()) == 1
    assert len(r_b.json()) == 1


def test_scoped_workspace_open_creates_session_in_that_product(client):
    p_a = _make_product(client, "acme", "widgets")

    r = client.post(f"/w/{p_a.slug}/workspace/open", data={}, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith(f"/w/{p_a.slug}/workspace/")

    session_id = loc.rsplit("/", 1)[-1]
    db = client._session_factory()
    sess = repository.get_session_row(db, session_id)
    assert sess.product_id == p_a.id
    db.close()
