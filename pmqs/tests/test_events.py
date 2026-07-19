"""test_events.py — the conversation activity-log event stream (interplay Wave 1)."""
import json
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs.db import Base
from pmqs import repository, warroom
from pmqs.web.render import render_workspace


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_add_event_creates_event_row(db):
    sess = repository.open_session(db, topic="t")
    ev = repository.add_event(db, sess.id, kind="lenses", label="⟳ Ran lenses — 3", tab="proposed")
    assert ev.role == "event"
    payload = json.loads(ev.content)
    assert payload["kind"] == "lenses" and payload["tab"] == "proposed"


def test_dialogue_only_excludes_events(db):
    sess = repository.open_session(db, topic="t")
    repository.add_message(db, sess.id, role="pm", content="hi")
    repository.add_event(db, sess.id, kind="outcome", label="§ Policy saved")
    repository.add_message(db, sess.id, role="assistant", content="reply")

    everything = repository.list_messages(db, sess.id)
    dialogue = repository.list_messages(db, sess.id, dialogue_only=True)
    assert len(everything) == 3
    assert [m.role for m in dialogue] == ["pm", "assistant"]


def test_events_never_reach_the_llm_context(db):
    # With LLM off, respond() uses the fallback, but the key invariant is that the event
    # row is not fed as conversation. We assert it's filtered from the dialogue list the
    # war-room builds its prompt from.
    sess = repository.open_session(db, topic="t")
    repository.add_event(db, sess.id, kind="outcome", label="§ Policy saved — secret label")
    warroom.respond(db, sess.id, "what do you think?")
    dialogue = repository.list_messages(db, sess.id, dialogue_only=True)
    assert all(m.role != "event" for m in dialogue)
    assert all("secret label" not in (m.content or "") for m in dialogue)


def test_render_shows_event_line_and_click_to_open(db):
    sess = repository.open_session(db, topic="t")
    repository.add_message(db, sess.id, role="pm", content="my take")
    repository.add_event(db, sess.id, kind="position_doc",
                         label="✎ Position document generated", tab="doc")
    msgs = repository.list_messages(db, sess.id)
    out = render_workspace(sess, msgs, [], [], None)
    assert "Position document generated" in out
    assert 'class="msg event event-open"' in out
    assert "showTab('doc')" in out
    # a tab-less event is not clickable
    repository.add_event(db, sess.id, kind="outcome", label="§ Policy saved")
    out2 = render_workspace(sess, repository.list_messages(db, sess.id), [], [], None)
    assert "Policy saved" in out2


def test_events_do_not_count_as_exchanges(db):
    # n_exchanges counts PM turns; events must not inflate it.
    sess = repository.open_session(db, topic="t")
    repository.add_message(db, sess.id, role="pm", content="q1")
    repository.add_event(db, sess.id, kind="lenses", label="⟳ Ran lenses")
    out = render_workspace(sess, repository.list_messages(db, sess.id), [], [], None)
    assert "<span>1</span> exchanges" in out
