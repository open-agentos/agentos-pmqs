"""test_outcome_export.py — Document/Meeting portability via Markdown (Wave 3)."""
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
from pmqs.outcomes.receipt import outcome_markdown


def test_markdown_document():
    md = outcome_markdown("document", {"title": "Drift brief", "body": "Body here."})
    assert md.startswith("# Drift brief")
    assert "Body here." in md


def test_markdown_meeting_includes_agenda_and_calendar():
    md = outcome_markdown(
        "meeting", {"title": "Roadmap review", "agenda": "1. X\n2. Y", "calendar_link": "https://cal/x"}
    )
    assert "## Agenda" in md and "1. X" in md
    assert "https://cal/x" in md


def test_markdown_policy_and_question():
    assert "cap retries" in outcome_markdown("policy", {"text": "cap retries at 3"})
    assert outcome_markdown("question", {"title": "Why?", "body": "note"}).startswith("# Why?")


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


def test_export_endpoint_serves_markdown(client):
    db = client._session_factory()
    o = repository.create_outcome(db, type="document", payload={"title": "Brief", "body": "text"})
    oid = o.id
    db.close()

    r = client.get(f"/outcomes/{oid}/export.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "# Brief" in r.text
    assert "Content-Disposition" not in r.headers  # inline (open-in-tab)


def test_export_download_sets_attachment(client):
    db = client._session_factory()
    o = repository.create_outcome(db, type="document", payload={"title": "Brief", "body": "t"})
    oid = o.id
    db.close()
    r = client.get(f"/outcomes/{oid}/export.md?download=1")
    assert "attachment" in r.headers.get("content-disposition", "")


def test_export_missing_outcome_404(client):
    r = client.get("/outcomes/nope/export.md")
    assert r.status_code == 404


def test_jira_selected_issue_commit_returns_clean_error(client):
    from pmqs import settings
    db = client._session_factory()
    settings.set_tracker(db, "jira")
    db.close()
    r = client.post("/workspace/open", data={}, follow_redirects=False)
    sid = r.headers["location"].split("/")[-1]
    out = client.post(f"/workspace/{sid}/outcome", data={"type": "issue", "title": "x"})
    assert out.status_code == 400
    assert "Jira" in out.json()["error"]
