from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_open_session_and_add_messages(db):
    q = repository.create_question(db, title="root q", source="system")
    s = repository.open_session(db, topic="war-room", question_id=q.id)
    repository.add_message(db, s.id, role="system", content="probe")
    repository.add_message(db, s.id, role="pm", content="answer")
    msgs = repository.list_messages(db, s.id)
    assert [m.role for m in msgs] == ["system", "pm"]
    assert msgs[1].content == "answer"


def test_session_branching(db):
    parent = repository.open_session(db, topic="parent")
    child = repository.open_session(db, topic="child", parent_id=parent.id)
    assert child.parent_id == parent.id


def test_close_session(db):
    s = repository.open_session(db, topic="t")
    repository.close_session(db, s.id)
    assert repository.get_session_row(db, s.id).status == "closed"


def test_position_doc_persists(db):
    s = repository.open_session(db, topic="t")
    repository.set_position_doc(db, s.id, {"summary": "x"})
    import json
    stored = json.loads(repository.get_session_row(db, s.id).position_doc)
    assert stored["summary"] == "x"
