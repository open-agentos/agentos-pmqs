"""B0b: opening a war-room for the same question reuses the session (Position Doc persists)."""
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


def _open(client, qid):
    r = client.post("/workspace/open", data={"question_id": qid}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"].split("/")[-1]


def test_reopen_same_question_reuses_session(client):
    db = client._sf()
    q = repository.create_question(db, title="ship or wait?", source="pm", status="proposed")
    qid = q.id
    db.close()

    sid1 = _open(client, qid)
    sid2 = _open(client, qid)
    assert sid1 == sid2  # reused, not a fresh session each time


def test_position_doc_persists_across_reopen(client):
    db = client._sf()
    q = repository.create_question(db, title="ship or wait?", source="pm", status="proposed")
    qid = q.id
    db.close()

    sid = _open(client, qid)
    # simulate a generated Position Doc persisted on the session
    db = client._sf()
    repository.set_position_doc(db, sid, {"summary": "S", "what_your_vote_means": "W",
                                          "background_impact": "B", "argument_for": "F",
                                          "rebuttal_for": "RF", "argument_against": "A",
                                          "rebuttal_against": "RA"})
    db.close()

    # reopen the same question → same session → doc still shown
    sid2 = _open(client, qid)
    assert sid2 == sid
    view = client.get(f"/workspace/{sid2}")
    assert "Voter-Guide format" in view.text  # the persisted doc renders
