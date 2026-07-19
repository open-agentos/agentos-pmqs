"""test_outcome_suggest_absence.py — Wave 4: suggestion + legible absence.

LLM forced off, so the suggestion path exercises the non-pushy fallback (type=None).
The close-reason signal and conversion helper are pure DB and fully covered here.
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
from pmqs.outcomes.suggest import suggest_outcome


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


# --- suggestion ---------------------------------------------------------------------

def test_suggest_is_non_pushy_when_llm_off(db):
    sess = repository.open_session(db, topic="whatever")
    s = suggest_outcome(db, sess)
    assert s["type"] is None          # no invented recommendation
    assert s["degraded"] is True
    assert s["rationale"]              # still guides the PM to pick


def test_suggest_endpoint_ok(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/suggest-outcome")
    assert out.status_code == 200
    assert "type" in out.json() and "rationale" in out.json()


def test_suggest_missing_session_404(client):
    assert client.post("/workspace/nope/suggest-outcome").status_code == 404


def test_suggest_creates_nothing(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    client.post(f"/workspace/{sid}/suggest-outcome")
    db = client._session_factory()
    assert repository.list_outcomes(db) == []
    db.close()


# --- close reason / legible absence -------------------------------------------------

def test_close_records_reason(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/close", data={"reason": "no_decision_yet"})
    assert out.status_code == 200
    assert out.json()["status"] == "closed"
    assert out.json()["close_reason"] == "no_decision_yet"


def test_close_reason_is_optional(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/close", data={})
    assert out.status_code == 200
    assert out.json()["close_reason"] is None   # never a gate


def test_unknown_close_reason_rejected(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/close", data={"reason": "bored"})
    assert out.status_code == 400


def test_close_missing_session_404(client):
    assert client.post("/workspace/nope/close", data={"reason": "no_decision_yet"}).status_code == 404


# --- conversion signal --------------------------------------------------------------

def test_conversion_separates_warranted_from_failure(db):
    # one session with an outcome, one closed "couldn't get what I needed", one open.
    s1 = repository.open_session(db, topic="produced")
    repository.create_outcome(db, type="document", payload={"title": "d"}, session_id=s1.id)
    s2 = repository.open_session(db, topic="failed")
    repository.close_session(db, s2.id, reason="couldnt_get_what_i_needed")
    repository.open_session(db, topic="still open")

    conv = repository.outcome_conversion(db)
    assert conv["sessions"] == 3
    assert conv["with_outcome"] == 1
    assert conv["closed_no_outcome"] == 1
    assert conv["reasons"]["couldnt_get_what_i_needed"] == 1


def test_session_with_outcome_is_not_counted_as_absence(db):
    # A session that both produced an outcome AND has a stray close_reason is not
    # "closed without outcome" — the outcome is what matters.
    s = repository.open_session(db, topic="both")
    repository.create_outcome(db, type="policy", payload={"text": "x"}, session_id=s.id)
    repository.close_session(db, s.id, reason="decided_nothing_to_record")
    conv = repository.outcome_conversion(db)
    assert conv["with_outcome"] == 1
    assert conv["closed_no_outcome"] == 0
