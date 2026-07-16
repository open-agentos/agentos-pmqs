"""API-level tests for the promote action (Shared Outcomes build-spec, Wave 2 item 5,
§4 rules 3 and 4)."""
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
    yield TestClient(app), db, product, me
    app.dependency_overrides.clear()
    db.close()


def _outcome(db, product, me, visibility):
    session = repository.open_session(
        db, topic="q", product_id=product.id, author_member_id=me.id, visibility=visibility
    )
    return repository.create_outcome(
        db, type="policy", payload={"text": "p"}, session_id=session.id,
        product_id=product.id, author_member_id=me.id,
    )


def test_promote_private_outcome_returns_promoted_at(ctx):
    client, db, product, me = ctx
    o = _outcome(db, product, me, "private")

    r = client.post(f"/outcomes/{o.id}/promote")
    assert r.status_code == 200
    assert r.json()["promoted_at"] is not None


def test_promote_already_shared_outcome_is_rejected(ctx):
    client, db, product, me = ctx
    o = _outcome(db, product, me, "shared")

    r = client.post(f"/outcomes/{o.id}/promote")
    assert r.status_code == 409


def test_promote_twice_is_rejected(ctx):
    """§4 rule 4: one-way. The second call is a caller who thinks something is hidden
    when it isn't -- that deserves a 409, not a shrug."""
    client, db, product, me = ctx
    o = _outcome(db, product, me, "private")

    assert client.post(f"/outcomes/{o.id}/promote").status_code == 200
    assert client.post(f"/outcomes/{o.id}/promote").status_code == 409


def test_promote_missing_outcome_is_404(ctx):
    client, _, _, _ = ctx
    assert client.post("/outcomes/does-not-exist/promote").status_code == 404


def test_ledger_json_excludes_another_members_private_room(ctx):
    client, db, product, me = ctx
    from pmqs.models import Member

    colleague = Member(display_name="Ada")
    db.add(colleague)
    db.commit()
    session = repository.open_session(
        db, topic="q", product_id=product.id, author_member_id=colleague.id, visibility="private"
    )
    hidden = repository.create_outcome(
        db, type="policy", payload={"text": "secret"}, session_id=session.id,
        product_id=product.id, author_member_id=colleague.id,
    )
    mine = _outcome(db, product, me, "shared")

    ids = {o["id"] for o in client.get("/api/outcomes").json()}
    assert mine.id in ids
    assert hidden.id not in ids
