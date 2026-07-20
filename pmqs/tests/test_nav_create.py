"""test_nav_create.py — the everpresent create affordance (rec 5).

Three things a PM should be able to do from any view: ask a question, start a war room
that ISN'T tied to a system-raised question (a self-directed strategic session), and
record an outcome directly. Plus the rail's collapse ergonomics.
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


# --- start a self-directed war room (rec 5 proper) ---

def test_war_room_from_a_topic_with_no_question(client):
    topic = "Are we over-investing in the enterprise tier?"
    r = client.post("/workspace/open", data={"topic": topic}, follow_redirects=False)
    assert r.status_code == 303
    sid = r.headers["location"].rsplit("/", 1)[-1]
    db = client._session_factory()
    sess = repository.get_session_row(db, sid)
    assert sess.topic == topic          # the prompt became the room's topic
    assert sess.question_id is None     # not tied to any inbox question
    db.close()
    # and the room renders with the topic in it
    assert topic in client.get(f"/workspace/{sid}").text


def test_open_from_question_still_wins_over_topic(client):
    # a question_id must still drive the topic (regression guard on the shared route)
    db = client._session_factory()
    q = repository.create_question(db, title="the real question", source="system")
    qid = q.id
    db.close()
    r = client.post("/workspace/open", data={"question_id": qid, "topic": "ignore me"},
                    follow_redirects=False)
    sid = r.headers["location"].rsplit("/", 1)[-1]
    db = client._session_factory()
    assert repository.get_session_row(db, sid).topic == "the real question"
    db.close()


# --- record an outcome directly (no session) ---

@pytest.mark.parametrize("otype,data", [
    ("policy", {"title": "Cap retries at 3 across services"}),
    ("document", {"title": "Enterprise tier one-pager", "body": "the case"}),
    ("meeting", {"title": "Tier strategy sync", "body": "agenda item"}),
    ("question", {"title": "Should we sunset the free tier?"}),
])
def test_record_direct_outcome_lands_in_ledger(client, otype, data):
    r = client.post("/outcomes/new", data={"type": otype, **data}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/outcomes")
    db = client._session_factory()
    outs = repository.list_ledger_outcomes(db, member_id=None, include_retired=True)
    assert len(outs) == 1
    assert outs[0].type == otype
    assert outs[0].session_id is None        # a 'direct' outcome, no war room
    db.close()


def test_issue_cannot_be_recorded_directly(client):
    # Issue means 'push to GitHub' — it belongs to the question -> war-room -> push flow
    r = client.post("/outcomes/new", data={"type": "issue", "title": "a bug"})
    assert r.status_code == 400


def test_direct_outcome_shows_in_the_rendered_ledger(client):
    client.post("/outcomes/new", data={"type": "policy", "title": "No deploys on Fridays"})
    html = client.get("/outcomes").text
    assert "No deploys on Fridays" in html
    assert "· direct" in html            # labelled as session-less


# --- the create menu + collapsible rail are present on rendered pages ---

def test_create_menu_and_rail_toggle_render(client):
    html = client.get("/").text
    assert 'id="create-wrap"' in html
    assert "pmqsToggleCreate" in html
    assert "pmqsCreateSubmit" in html               # prefix-aware submit from live JS
    assert 'onclick="pmqsToggleRail()"' in html     # collapse toggle
    assert "#rail.collapsed" in html                # collapse CSS present
    # all three create actions offered
    assert "Ask a question" in html
    assert "Start a war room" in html
    assert "Record an outcome" in html
