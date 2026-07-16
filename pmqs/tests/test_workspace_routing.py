"""Tests for workspace-scoped routing under /w/{workspace_slug}/... (issue #56)."""
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


def _make_workspace(client, org, repo, nickname=None):
    db = client._session_factory()
    product = products.get_or_create_product(db, org=org, repo=repo)
    ws = products.create_workspace(db, product=product, nickname=nickname)
    db.close()
    return ws


def test_scoped_inbox_only_shows_that_workspaces_questions(client):
    ws_a = _make_workspace(client, "acme", "widgets")
    ws_b = _make_workspace(client, "acme", "gizmos")

    db = client._session_factory()
    repository.create_question(db, title="Widgets question", source="pm", workspace_id=ws_a.id)
    repository.create_question(db, title="Gizmos question", source="pm", workspace_id=ws_b.id)
    db.close()

    r_a = client.get(f"/w/{ws_a.slug}/")
    r_b = client.get(f"/w/{ws_b.slug}/")
    assert "Widgets question" in r_a.text
    assert "Gizmos question" not in r_a.text
    assert "Gizmos question" in r_b.text
    assert "Widgets question" not in r_b.text


def test_unknown_workspace_slug_is_404(client):
    r = client.get("/w/does-not-exist/")
    assert r.status_code == 404


def test_scoped_quick_add_lands_in_the_right_workspace(client):
    ws_a = _make_workspace(client, "acme", "widgets")
    ws_b = _make_workspace(client, "acme", "gizmos")

    r = client.post(f"/w/{ws_a.slug}/quick-add", data={"title": "New idea"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/w/{ws_a.slug}/"

    db = client._session_factory()
    assert len(repository.list_questions(db, workspace_id=ws_a.id)) == 1
    assert len(repository.list_questions(db, workspace_id=ws_b.id)) == 0
    db.close()


def test_legacy_unprefixed_routes_still_work_unchanged(client):
    # No workspace_slug at all -- pre-#56 behaviour: falls back to whatever workspace(s)
    # exist, doesn't 404, doesn't require a slug.
    r = client.post("/quick-add", data={"title": "Legacy add"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    r2 = client.get("/")
    assert r2.status_code == 200
    assert "Legacy add" in r2.text


def test_scoped_outcomes_ledger_isolated_per_workspace(client):
    ws_a = _make_workspace(client, "acme", "widgets")
    ws_b = _make_workspace(client, "acme", "gizmos")

    db = client._session_factory()
    repository.create_outcome(db, type="document", payload={"title": "A doc"}, workspace_id=ws_a.id)
    repository.create_outcome(db, type="document", payload={"title": "B doc"}, workspace_id=ws_b.id)
    db.close()

    r_a = client.get(f"/w/{ws_a.slug}/api/outcomes")
    r_b = client.get(f"/w/{ws_b.slug}/api/outcomes")
    assert len(r_a.json()) == 1
    assert len(r_b.json()) == 1


def test_scoped_workspace_open_creates_session_in_that_workspace(client):
    ws_a = _make_workspace(client, "acme", "widgets")

    r = client.post(f"/w/{ws_a.slug}/workspace/open", data={}, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith(f"/w/{ws_a.slug}/workspace/")

    session_id = loc.rsplit("/", 1)[-1]
    db = client._session_factory()
    sess = repository.get_session_row(db, session_id)
    assert sess.workspace_id == ws_a.id
    db.close()
