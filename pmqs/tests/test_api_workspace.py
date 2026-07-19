"""API-level tests for Workspace + typed outcomes (Phase 2). LLM forced off."""
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
        poolclass=StaticPool,  # single shared connection so the in-memory DB persists
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
    # Prevent startup init_db from touching the real file DB.
    with TestClient(app) as c:
        c._session_factory = TestingSession  # expose for assertions
        yield c
    app.dependency_overrides.clear()


def test_open_and_view_workspace(client):
    # create a question via the DB the app uses
    db = client._session_factory()
    q = repository.create_question(db, title="Ship or wait?", source="system",
                                   evidence=[{"type": "issue", "ref": "#47", "url": "u"}])
    qid = q.id
    db.close()

    r = client.post("/workspace/open", data={"question_id": qid}, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/workspace/")

    view = client.get(loc)
    assert view.status_code == 200
    assert "Ship or wait?" in view.text
    assert 'id="view-inbox"' in view.text  # other views preserved


def test_message_persists(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    m = client.post(f"/workspace/{sid}/message", data={"content": "my take"}, follow_redirects=False)
    assert m.status_code == 303
    view = client.get(f"/workspace/{sid}")
    assert "my take" in view.text
    # LLM off → fallback assistant message present, no crash
    assert "LLM unavailable" in view.text


def test_run_lenses_llm_off_is_safe(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    lensed = client.post(f"/workspace/{sid}/run-lenses", follow_redirects=False)
    assert lensed.status_code == 303  # no crash even with LLM off


def test_policy_outcome_no_github_ref(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/outcome",
                      data={"type": "policy", "title": "retry budget", "body": "cap retries"})
    assert out.status_code == 200
    assert out.json()["github_ref"] is None
    assert out.json()["type"] == "policy"


def test_document_outcome_persists(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/outcome",
                      data={"type": "document", "title": "briefing"})
    assert out.status_code == 200
    assert out.json()["type"] == "document"


def test_outcome_response_carries_receipt(client):
    # Wave 1: every committed outcome tells the war room its title + where it lives.
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/outcome",
                      data={"type": "document", "title": "Drift briefing"})
    j = out.json()
    assert j["title"] == "Drift briefing"
    assert j["location"]["kind"] == "ledger"
    assert j["location"]["url"].endswith("/outcomes")


def test_policy_receipt_title_is_its_text(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/outcome",
                      data={"type": "policy", "title": "cap retries", "body": "cap retries at 3"})
    j = out.json()
    assert j["title"] == "cap retries at 3"
    assert j["location"]["kind"] == "ledger"


def test_unknown_outcome_type_rejected(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/outcome", data={"type": "banana"})
    assert out.status_code == 400


def test_draft_endpoint_returns_editable_fields(client):
    # Wave 2: drafting is generate-not-persist; LLM off → degraded stub, still usable.
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    d = client.post(f"/workspace/{sid}/draft", data={"type": "document"})
    assert d.status_code == 200
    j = d.json()
    assert j["type"] == "document"
    assert set(j["fields"].keys()) == {"title", "body"}
    # nothing persisted by drafting
    from pmqs import repository
    db = client._session_factory()
    assert repository.list_outcomes(db) == []
    db.close()


def test_draft_unknown_type_rejected(client):
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    d = client.post(f"/workspace/{sid}/draft", data={"type": "banana"})
    assert d.status_code == 400


def test_draft_missing_session_404(client):
    d = client.post("/workspace/nope/draft", data={"type": "document"})
    assert d.status_code == 404
