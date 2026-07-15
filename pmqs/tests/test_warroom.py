from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, warroom


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_respond_persists_assistant_reply(db, monkeypatch):
    monkeypatch.setattr(warroom.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(warroom.llm, "complete", lambda s, u, **k: "What's the actual risk?")
    q = repository.create_question(db, title="ship or wait?", source="system",
                                   evidence=[{"type": "issue", "ref": "#47", "url": "u"}])
    sess = repository.open_session(db, topic="ship or wait", question_id=q.id)
    msg = warroom.respond(db, sess.id, "I think we should ship.")
    assert msg.role == "assistant"
    assert msg.content == "What's the actual risk?"
    roles = [m.role for m in repository.list_messages(db, sess.id)]
    assert roles == ["pm", "assistant"]


def test_respond_survives_llm_failure(db, monkeypatch):
    monkeypatch.setattr(warroom.llm, "is_enabled", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(warroom.llm, "complete", boom)
    sess = repository.open_session(db, topic="t")
    msg = warroom.respond(db, sess.id, "hello")
    assert msg.role == "assistant"
    assert "LLM unavailable" in msg.content  # graceful fallback, no crash


def test_respond_llm_off_uses_fallback(db, monkeypatch):
    monkeypatch.setattr(warroom.llm, "is_enabled", lambda: False)
    sess = repository.open_session(db, topic="t")
    msg = warroom.respond(db, sess.id, "hello")
    assert "LLM unavailable" in msg.content
