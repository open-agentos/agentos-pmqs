"""Polish-phase tests: B0a, B0b, B1, B2, B3, B4, B6, H1, H2."""
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
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
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
        c._sf = TestingSession
        yield c
    app.dependency_overrides.clear()


# --- B1: Inbox excludes dismissed/promoted ---
def test_list_questions_excludes_dismissed_and_promoted(db):
    repository.create_question(db, title="proposed", source="pm")
    saved = repository.create_question(db, title="saved", source="pm")
    repository.update_question_status(db, saved.id, "saved")
    dis = repository.create_question(db, title="dismissed", source="pm")
    repository.update_question_status(db, dis.id, "dismissed")
    prom = repository.create_question(db, title="promoted", source="pm")
    repository.update_question_status(db, prom.id, "promoted")

    titles = {q.title for q in repository.list_questions(db)}
    assert titles == {"proposed", "saved"}
    # include_all sees everything
    assert len(repository.list_questions(db, include_all=True)) == 4


# --- B1/H2: source filter ---
def test_list_questions_source_filter(db):
    repository.create_question(db, title="pmq", source="pm")
    repository.create_question(db, title="sysq", source="system")
    assert [q.title for q in repository.list_questions(db, source="pm")] == ["pmq"]
    assert [q.title for q in repository.list_questions(db, source="system")] == ["sysq"]


# --- B0a: home never swaps data source; always lands on inbox view ---
def test_home_is_inbox_view_and_no_github_swap(client):
    # empty store → empty-state, NOT a live GitHub dump
    r = client.get("/")
    assert r.status_code == 200
    assert "Your Inbox is empty" in r.text
    assert "showView('inbox')" in r.text  # forced inbox view

    # add a question → home still renders the inbox (not workspace), shows it
    db = client._sf()
    repository.create_question(db, title="a real question", source="pm", status="proposed")
    db.close()
    r2 = client.get("/")
    assert "a real question" in r2.text
    assert "showView('inbox')" in r2.text


# --- B2: status button redirects (not JSON) ---
def test_status_redirects_and_dismiss_removes_from_inbox(client):
    db = client._sf()
    q = repository.create_question(db, title="dismiss me", source="pm", status="proposed")
    qid = q.id
    db.close()
    r = client.post(f"/questions/{qid}/status", data={"status": "dismissed"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # no longer in the inbox
    assert "dismiss me" not in client.get("/").text


# --- B4: news flash banner ---
def test_news_flash_banner(client):
    assert "new question" in client.get("/?news=3").text
    assert "Nothing relevant" in client.get("/?news=none").text
    assert "Nothing relevant" not in client.get("/").text


# --- B6: proposed tab scoped to session ---
def test_session_proposed_is_scoped(db):
    sA = repository.open_session(db, topic="A")
    sB = repository.open_session(db, topic="B")
    repository.create_question(db, title="from A", source="system", status="proposed",
                               origin_session_id=sA.id)
    repository.create_question(db, title="from B", source="system", status="proposed",
                               origin_session_id=sB.id)
    a_titles = {q.title for q in repository.list_session_proposed(db, sA.id)}
    assert a_titles == {"from A"}


# --- H1: HTML 404 for browser route ---
def test_workspace_404_is_html(client):
    r = client.get("/workspace/does-not-exist")
    assert r.status_code == 404
    assert "<html" in r.text.lower()
    assert "Back to Inbox" in r.text
