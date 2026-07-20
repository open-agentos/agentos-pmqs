"""test_live_ledger.py — the ledger is live, not terminal (edit / remove / reopen).

Before this, a committed outcome was a dead end: no edit, no remove, no way back into the
room. These cover the three actions plus their guards — soft-delete keeps history, remove
returns the question to the Inbox, edit is hosted-types-only, and every action is
owner-guarded because the ledger is Product-scoped and can show a colleague's rows.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs import repository


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


# --- repository level ---

def test_update_payload_edits_in_place(db):
    o = repository.create_outcome(db, type="document", payload={"title": "old", "body": "b"})
    repository.update_outcome_payload(db, o.id, {"title": "new", "body": "b2"})
    assert repository.outcome_payload(o) == {"title": "new", "body": "b2"}
    # lifecycle untouched
    assert o.retired_at is None


def test_reopen_session_inverts_close(db):
    s = repository.open_session(db, topic="t")
    repository.close_session(db, s.id, reason="decided nothing to record")
    assert s.status == "closed" and s.close_reason
    repository.reopen_session(db, s.id)
    assert s.status == "open" and s.closed_at is None and s.close_reason is None


def test_ledger_hides_retired_by_default(db):
    from pmqs import members
    me = members.current_member_id(db)
    o = repository.create_outcome(db, type="document", payload={"title": "d"})
    assert len(repository.list_ledger_outcomes(db, member_id=me)) == 1
    repository.deactivate_outcome(db, o.id)
    assert repository.list_ledger_outcomes(db, member_id=me) == []            # gone from the ledger
    assert len(repository.list_ledger_outcomes(db, member_id=me, include_retired=True)) == 1  # history kept


# --- endpoint level ---

def test_edit_endpoint_changes_a_document(client):
    db = client._session_factory()
    o = repository.create_outcome(db, type="document", payload={"title": "old", "body": "x"})
    oid = o.id
    db.close()
    r = client.post(f"/outcomes/{oid}/edit", data={"title": "Refined brief", "body": "y"})
    assert r.status_code == 200 and r.json()["title"] == "Refined brief"
    db = client._session_factory()
    assert repository.outcome_payload(repository.get_outcome(db, oid))["title"] == "Refined brief"
    db.close()


def test_issue_is_not_editable_in_the_ledger(client):
    db = client._session_factory()
    o = repository.create_outcome(db, type="issue", payload={"title": "bug"})
    oid = o.id
    db.close()
    r = client.post(f"/outcomes/{oid}/edit", data={"title": "x"})
    assert r.status_code == 400


def test_remove_retires_and_returns_question_to_inbox(client):
    # room opened on a question, outcome commit answered it (Wave 1), now remove it
    db = client._session_factory()
    q = repository.create_question(db, title="ship or wait?", source="system")
    qid = q.id
    db.close()
    sid = client.post("/workspace/open", data={"question_id": qid},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[-1]
    client.post(f"/workspace/{sid}/outcome", data={"type": "document", "title": "brief", "body": "b"})
    db = client._session_factory()
    oid = repository.list_ledger_outcomes(db, member_id=None, include_retired=True)[0].id
    assert repository.get_question(db, qid).status == "answered"
    db.close()

    r = client.post(f"/outcomes/{oid}/remove")
    assert r.status_code == 200 and r.json()["returned_to_inbox"] == "ship or wait?"
    db = client._session_factory()
    assert repository.get_question(db, qid).status == "saved"          # back in the Inbox
    assert repository.get_outcome(db, oid).retired_at is not None      # soft-deleted
    db.close()


def test_reopen_returns_room_url(client):
    db = client._session_factory()
    q = repository.create_question(db, title="q", source="system")
    qid = q.id
    db.close()
    sid = client.post("/workspace/open", data={"question_id": qid},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[-1]
    client.post(f"/workspace/{sid}/outcome", data={"type": "policy", "body": "cap at 3"})
    db = client._session_factory()
    oid = repository.list_ledger_outcomes(db, member_id=None, include_retired=True)[0].id
    db.close()
    r = client.post(f"/outcomes/{oid}/reopen")
    assert r.status_code == 200 and r.json()["url"] == f"/workspace/{sid}"


def test_actions_are_owner_guarded(client):
    # an outcome authored by someone else must not be editable/removable
    db = client._session_factory()
    o = repository.create_outcome(db, type="document", payload={"title": "theirs"},
                                  author_member_id="another-member")
    oid = o.id
    db.close()
    assert client.post(f"/outcomes/{oid}/edit", data={"title": "x"}).status_code == 403
    assert client.post(f"/outcomes/{oid}/remove").status_code == 403


def test_owned_rows_carry_action_buttons(client):
    db = client._session_factory()
    repository.create_outcome(db, type="document", payload={"title": "mine"})
    db.close()
    html = client.get("/outcomes").text
    assert "pmqsOutcomeEdit" in html and "pmqsOutcomeRemove" in html
