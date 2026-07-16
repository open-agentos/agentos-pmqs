"""Route-level tests for the Workspace list view (build-spec §10.1, Wave 2 item 7).

These exist because render.py splices into app.html via regex anchored on its markup,
TEMPLATE-CONTRACT.md says no test asserts on that markup, and a broken anchor surfaces
only at REQUEST time -- or worse, renders the fixture silently. A unit test on the
renderer wouldn't catch a broken route; these hit the real app.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products, repository
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs.models import Member


@pytest.fixture
def ctx():
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
    db = TestingSession()
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    me = members.get_or_create_default_member(db)
    ada = Member(display_name="Ada Lovelace")
    db.add(ada)
    db.commit()
    repository.open_session(db, topic="Shared room by Ada", product_id=product.id,
                            author_member_id=ada.id, visibility="shared")
    repository.open_session(db, topic="ADAS PRIVATE ROOM", product_id=product.id,
                            author_member_id=ada.id, visibility="private")
    repository.open_session(db, topic="My own room", product_id=product.id,
                            author_member_id=me.id, visibility="shared")
    yield TestClient(app)
    app.dependency_overrides.clear()
    db.close()


def test_list_route_renders_real_rooms(ctx):
    r = ctx.get("/workspaces")
    assert r.status_code == 200
    assert "Shared room by Ada" in r.text
    assert "My own room" in r.text
    # the fixture must be gone -- a silently-unspliced page is the template-contract trap
    assert "No workspaces yet." not in r.text


def test_list_route_never_leaks_a_private_room(ctx):
    for url in ["/workspaces", "/workspaces?owner=mine", "/workspaces?owner=not_mine"]:
        assert "ADAS PRIVATE ROOM" not in ctx.get(url).text


def test_owned_by_me_filter_route(ctx):
    body = ctx.get("/workspaces?owner=mine").text
    assert "My own room" in body
    assert "Shared room by Ada" not in body


def test_not_owned_by_me_filter_route(ctx):
    body = ctx.get("/workspaces?owner=not_mine").text
    assert "Shared room by Ada" in body
    assert "My own room" not in body


def test_a_garbage_filter_does_not_500(ctx):
    """A bad query string must not be able to take the page down; 'any' is safe because
    visibility is enforced in the query regardless of the chip."""
    r = ctx.get("/workspaces?owner=garbage")
    assert r.status_code == 200
    assert "Shared room by Ada" in r.text
