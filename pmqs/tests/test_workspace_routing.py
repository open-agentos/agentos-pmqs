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
    # ...and the URL it points at exists. Asserting the redirect's SHAPE and never
    # following it is exactly how #104 shipped green: this test pinned the very URL
    # that 404'd.
    assert client.get(loc).status_code == 200

    session_id = loc.rsplit("/", 1)[-1]
    db = client._session_factory()
    sess = repository.get_session_row(db, session_id)
    assert sess.product_id == p_a.id
    db.close()


# --- #104: the war room is reachable from a product-prefixed page ---
#
# GET /workspace/{session_id} had no /w/{slug}/ twin while TWO callers built the
# prefixed URL -- open_workspace()'s redirect (above) and the Workspaces list's
# pmqsOpenRoom(). So the war room 404'd from anywhere under /w/{slug}/, and since the
# Product switcher links to /w/{slug}/, switching product broke the inbox -> room loop.


def _room(client, repo="agentos-pmqs"):
    p = _make_product(client, "open-agentos", repo)
    db = client._session_factory()
    sess = repository.open_session(db, topic="A room", product_id=p.id)
    out = (p.slug, sess.id)
    db.close()
    return out


def test_prefixed_room_url_renders(client):
    slug, sid = _room(client)
    r = client.get(f"/w/{slug}/workspace/{sid}")
    assert r.status_code == 200
    assert 'id="view-workspace"' in r.text


def test_unprefixed_room_url_still_renders(client):
    """The session-keyed form is documented and the room's own XHR calls rely on it."""
    _, sid = _room(client)
    assert client.get(f"/workspace/{sid}").status_code == 200


def test_reopening_an_existing_room_from_a_prefixed_inbox_does_not_404(client):
    """open_workspace has two redirect branches; the reuse branch builds the same URL."""
    slug, _ = _room(client)
    db = client._session_factory()
    p = products.get_product_by_slug(db, slug)
    qid = repository.create_question(db, title="Q", source="pm", product_id=p.id).id
    db.close()

    first = client.post(f"/w/{slug}/workspace/open", data={"question_id": qid},
                        follow_redirects=False)
    again = client.post(f"/w/{slug}/workspace/open", data={"question_id": qid},
                        follow_redirects=False)
    assert first.headers["location"] == again.headers["location"]  # reuse branch
    assert client.get(again.headers["location"]).status_code == 200


def test_the_workspaces_list_links_somewhere_that_exists(client):
    """pmqsOpenRoom() built this URL against a route that didn't exist."""
    slug, sid = _room(client)
    r = client.get(f"/w/{slug}/workspaces")
    assert f"'/w/{slug}/workspace/'" in r.text  # the JS builder
    assert client.get(f"/w/{slug}/workspace/{sid}").status_code == 200


def test_a_room_under_the_wrong_products_url_is_404_not_a_render(client):
    """Serving product A's room under a URL claiming product B is a crossed stream."""
    slug_a, sid_a = _room(client, "agentos-pmqs")
    slug_b, _ = _room(client, "agentos")
    assert slug_a != slug_b
    assert client.get(f"/w/{slug_b}/workspace/{sid_a}").status_code == 404
    assert client.get(f"/w/{slug_a}/workspace/{sid_a}").status_code == 200


def test_unknown_session_is_404_on_both_mounts(client):
    slug, _ = _room(client)
    assert client.get("/workspace/does-not-exist").status_code == 404
    assert client.get(f"/w/{slug}/workspace/does-not-exist").status_code == 404


def test_the_rail_comes_from_the_session_not_the_url(client):
    """Both mounts put the same product in the rail: the Session carries its own
    product_id, so the URL is navigation, not scope."""
    slug, sid = _room(client)
    for html in (client.get(f"/w/{slug}/workspace/{sid}").text,
                 client.get(f"/workspace/{sid}").text):
        assert f'id="ps-settings" href="/w/{slug}/settings"' in html


def test_nav_reads_workspaces_not_workspace(client):
    """#105 -- it opens a list."""
    assert '<div class="nav-item" data-nav="workspace">Workspaces' in client.get("/").text
