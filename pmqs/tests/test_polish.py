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


# --- Unified refresh report banner (repo + news in one) ---
def test_refresh_report_banner_covers_both_sources(client):
    from pmqs.refresh import RefreshReport, SourceResult

    # repo produced questions; news had no new stories
    tok = RefreshReport(SourceResult("generated", 3),
                        SourceResult("nothing_new", 0)).encode()
    html = client.get(f"/?refresh={tok}").text
    assert "Refresh complete" in html
    assert "3 new question" in html
    assert "Repo: 3 new from structural triggers." in html
    assert "no new stories for your watchlist" in html
    # no token → no banner
    assert "Refresh complete" not in client.get("/").text


def test_refresh_report_banner_explains_zero_and_flags_fixables(client):
    from pmqs.refresh import RefreshReport, SourceResult

    # clean repo (fine) + missing key (fixable) → banner explains each, net zero
    tok = RefreshReport(
        SourceResult("clean", 0, "scanned 1 open issue; none stale (>14d) or label-conflicting"),
        SourceResult("no_key", 0, "set BRAVE_API_KEY in your environment"),
    ).encode()
    html = client.get(f"/?refresh={tok}").text
    assert "no new questions" in html
    assert "nothing to raise" in html          # clean repo reads as an explanation
    assert "no Brave API key" in html           # missing key is called out specifically
    assert "BRAVE_API_KEY" in html
    # a malformed token must never crash the page
    assert client.get("/?refresh=not-valid-base64!!!").status_code == 200


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


# --- Persistent Refresh button + refresh banner ---
def test_inbox_has_persistent_refresh_button(client):
    # header Refresh button present even when the Inbox has questions
    db = client._sf()
    repository.create_question(db, title="existing q", source="pm", status="proposed")
    db.close()
    html = client.get("/").text
    assert "⟳ Refresh" in html
    assert "pmqsRefresh()" in html


def test_refresh_endpoint_redirects_with_report_token(client):
    # Fake a clean repo (no open issues) so the structural pass fires nothing; the
    # redirect carries an opaque refresh report token that decodes to a real banner.
    import pmqs.refresh as refresh_mod
    from pmqs.refresh import RefreshReport

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_state(self):
            return {"issues": [], "labels": []}

    orig = refresh_mod.AgentOSClient
    refresh_mod.AgentOSClient = _FakeClient
    try:
        r = client.post("/refresh", follow_redirects=False)
        assert r.status_code == 303
        loc = r.headers["location"]
        assert "refresh=" in loc
        token = loc.split("refresh=", 1)[1]
        report = RefreshReport.decode(token)
        assert report is not None
        assert report.repo.code == "clean"       # ran fine, nothing to raise
        assert report.news.code == "no_key"       # offline test: no Brave key
    finally:
        refresh_mod.AgentOSClient = orig


# --- H1: HTML 404 for browser route ---
def test_workspace_404_is_html(client):
    r = client.get("/workspace/does-not-exist")
    assert r.status_code == 404
    assert "<html" in r.text.lower()
    assert "Back to Inbox" in r.text

