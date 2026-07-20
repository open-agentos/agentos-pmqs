"""Position Document generation fixes (dogfooding):

1. Clicking Generate in a war room with no linked question used to silently no-op --
   the busy line flashed and the pane re-rendered the same empty state. Now it
   generates from the room's topic, and a room with neither question nor topic gets a
   legible message instead of a silent flash.
2. Nested-dict LLM output (e.g. what_your_vote_means -> {yes, no}) is flattened to
   readable text AT GENERATION TIME, so the persisted doc never holds a Python repr.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pmqs.position_doc as position_doc
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs import repository


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng, future=True)

    def _override():
        s = TS()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    c = TestClient(app, raise_server_exceptions=False)
    c._sf = TS
    yield c
    app.dependency_overrides.clear()


def _mock_llm(monkeypatch, result):
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(position_doc.llm, "complete_json",
                        lambda system, user, *, settings_cfg=None, max_tokens=None: result)


NESTED = {
    "summary": "S",
    "what_your_vote_means": {"yes": "Commit resources", "no": "Deprioritize"},
    "background_impact": {"context": "Notion dominant", "market_signal": "Composio shipped"},
    "argument_for": "F", "rebuttal_for": "RF", "argument_against": "A", "rebuttal_against": "RA",
}


# --- 1. the flash-then-blank fix ----------------------------------------------------

def test_generate_works_for_room_with_topic_but_no_question(client, monkeypatch):
    _mock_llm(monkeypatch, NESTED)
    s = client._sf()
    sess = repository.open_session(s, topic="Should we gate agentos apply?")  # no question_id
    sid = sess.id
    s.commit(); s.close()

    r = client.post(f"/workspace/{sid}/position-doc", headers={"X-PMQS-Ajax": "1"})
    j = r.json()
    assert r.status_code == 200
    assert "generated" in j["event_html"]                 # not a silent no-op
    assert "pmqsGenDoc" not in j["tab_html"]              # a real doc, not the empty-state button
    assert "Commit resources" in j["tab_html"]

    s = client._sf()
    got = repository.get_session_row(s, sid)
    assert got.position_doc is not None                   # persisted
    s.close()


def test_empty_room_reports_legibly_instead_of_silent(client, monkeypatch):
    _mock_llm(monkeypatch, NESTED)
    s = client._sf()
    sess = repository.open_session(s)  # no question, no topic
    sid = sess.id
    s.commit(); s.close()

    r = client.post(f"/workspace/{sid}/position-doc", headers={"X-PMQS-Ajax": "1"})
    j = r.json()
    assert "Nothing to generate" in j["event_html"]       # says why, doesn't just flash


def test_linked_question_still_used_when_present(client, monkeypatch):
    _mock_llm(monkeypatch, NESTED)
    s = client._sf()
    q = repository.create_question(s, title="Q title", source="system", description="body")
    sess = repository.open_session(s, topic="Q title", question_id=q.id)
    sid = sess.id
    s.commit(); s.close()

    r = client.post(f"/workspace/{sid}/position-doc", headers={"X-PMQS-Ajax": "1"})
    assert "generated" in r.json()["event_html"]


# --- 2. generation-time dict normalization (the JSON-in-doc root cause) --------------

def test_nested_dict_is_flattened_at_generation_time(db_free=None):
    """The persisted doc must hold readable text, not a Python dict repr -- fixing it at
    render alone is too late because generate() used to str() it into the DB first."""
    from types import SimpleNamespace
    from sqlalchemy import create_engine as ce
    from sqlalchemy.orm import sessionmaker as sm
    eng = ce("sqlite:///:memory:", future=True); Base.metadata.create_all(eng)
    s = sm(bind=eng, future=True)()

    position_doc.llm.is_enabled = lambda: True
    position_doc.llm.complete_json = (
        lambda system, user, *, settings_cfg=None, max_tokens=None: NESTED)
    subject = SimpleNamespace(title="T", description="", evidence_list=[], evidence=[],
                              product_id=None, lens_tags_list=[])
    doc = position_doc.generate(s, subject)
    # stored field is text, no braces / quotes-around-keys repr
    assert isinstance(doc["what_your_vote_means"], str)
    assert "{" not in doc["what_your_vote_means"]
    assert "Commit resources" in doc["what_your_vote_means"]
    assert "**Yes:**" in doc["what_your_vote_means"]
    s.close()


def test_normalize_doc_field_shapes():
    n = position_doc.normalize_doc_field
    assert n(None) == ""
    assert n("x") == "x"
    assert n({"a": "1", "b": "2"}) == "**A:** 1\n\n**B:** 2"
    assert n(["p", "q"]) == "- p\n- q"
    assert n(7) == "7"
