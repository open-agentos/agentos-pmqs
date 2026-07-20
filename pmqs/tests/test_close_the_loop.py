"""test_close_the_loop.py — committing an outcome resolves the question that spawned it.

The dead end this covers: before this, the outcome bar POSTed {type,title,body} and never
touched the originating Inbox question. A PM could spend a war-room session producing a
Document/Meeting/Policy and the question sat in the Inbox untouched forever — work happened,
nothing moved, no momentum was felt. Now committing any outcome marks its question
'answered' (via the session's question_id), so it leaves the Inbox and shows in the ledger
as decided.
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


def _open_room_on_question(client, title="Ship a mitigation, or keep blocking on #47?"):
    db = client._session_factory()
    q = repository.create_question(db, title=title, source="system",
                                   evidence=[{"type": "issue", "ref": "#47", "url": "u"}])
    qid = q.id
    db.close()
    r = client.post("/workspace/open", data={"question_id": qid}, follow_redirects=False)
    assert r.status_code == 303
    sid = r.headers["location"].rsplit("/", 1)[-1]
    return qid, sid


# --- repository-level: the join and the status ---

def test_session_question_resolves_the_join():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    q = repository.create_question(db, title="Cut the retry budget?", source="system")
    s = repository.open_session(db, question_id=q.id, topic=q.title)
    assert repository.session_question(db, s.id).id == q.id
    # a self-directed room (no question) resolves to nothing, doesn't raise
    s2 = repository.open_session(db, topic="free-form")
    assert repository.session_question(db, s2.id) is None
    assert repository.session_question(db, None) is None


def test_mark_answered_leaves_inbox():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    q = repository.create_question(db, title="q", source="system")
    assert q.id in {x.id for x in repository.list_questions(db)}
    repository.mark_question_answered(db, q.id)
    assert q.id not in {x.id for x in repository.list_questions(db)}  # gone from Inbox
    assert repository.get_question(db, q.id).status == "answered"      # but not destroyed


# --- endpoint-level: committing a hosted outcome closes the loop ---

@pytest.mark.parametrize("otype,fields", [
    ("document", {"title": "Drift brief", "body": "the case"}),
    ("meeting", {"title": "Roadmap review", "agenda": "one item"}),
    ("policy", {"body": "cap retries at 3"}),
    ("question", {"title": "re-check the 20% cohort?"}),
])
def test_committing_outcome_resolves_the_question(client, otype, fields):
    qid, sid = _open_room_on_question(client)
    r = client.post(f"/workspace/{sid}/outcome", data={"type": otype, **fields})
    assert r.status_code == 200
    body = r.json()
    # the receipt names the question it closed
    assert body["resolved_question"]
    # the question is answered and out of the Inbox
    db = client._session_factory()
    assert repository.get_question(db, qid).status == "answered"
    assert qid not in {q.id for q in repository.list_questions(db)}
    db.close()


def test_self_directed_room_commits_without_a_question(client):
    # A room opened with no question (question_id empty) must still commit cleanly and
    # simply resolve nothing — the fallback must not fabricate or crash.
    r = client.post("/workspace/open", data={"question_id": ""}, follow_redirects=False)
    sid = r.headers["location"].rsplit("/", 1)[-1]
    r = client.post(f"/workspace/{sid}/outcome", data={"type": "document", "title": "adhoc", "body": "b"})
    assert r.status_code == 200
    assert r.json()["resolved_question"] is None


def test_ledger_shows_the_resolved_question(client):
    qid, sid = _open_room_on_question(client, title="Should the CLI verify catch drift?")
    client.post(f"/workspace/{sid}/outcome", data={"type": "document", "title": "Verify-step brief", "body": "x"})
    html = client.get("/outcomes").text
    assert "resolved:" in html
    assert "Should the CLI verify catch drift?" in html
