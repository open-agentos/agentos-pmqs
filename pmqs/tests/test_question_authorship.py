"""Tests for Question authorship (Shared Outcomes build-spec §7 "ALTERED question +
author_member_id", §4 rule 5, §5).

This closes a gap between §7 and §9: §7's target schema alters `question`, but Wave 1's
work-item table has no item for it, so it would otherwise never get built. It is needed
before Wave 2 item 5, whose acceptance criterion is "Inbox reads remain member-scoped --
assert this with a test": there is nothing to scope an inbox read BY without this column.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, repository
from pmqs.db import Base
from pmqs.models import Member, Question


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    yield session
    session.close()


def test_new_question_gets_an_author(db):
    q = repository.create_question(db, title="Are we losing on price?", source="system")
    assert q.author_member_id == members.get_or_create_default_member(db).id


def test_question_author_can_be_set_explicitly(db):
    other = Member(display_name="Someone else")
    db.add(other)
    db.commit()

    q = repository.create_question(db, title="A colleague's question", source="pm",
                                   author_member_id=other.id)
    assert q.author_member_id == other.id


@pytest.mark.parametrize("source", ["system", "pm", "news"])
def test_every_question_source_gets_an_owner(source, db):
    """Inbox items have an owner however they were raised -- PM quick-add, lens pass, or
    news -- because the Inbox is always member-scoped (§4 rule 5)."""
    q = repository.create_question(db, title=f"raised by {source}", source=source)
    assert q.author_member_id is not None


def test_questions_are_separable_by_member(db):
    """The property Wave 2 item 5 has to assert: one member's inbox is not another's."""
    from sqlalchemy import select

    mine = members.get_or_create_default_member(db)
    theirs = Member(display_name="Someone else")
    db.add(theirs)
    db.commit()

    repository.create_question(db, title="mine", source="system")
    repository.create_question(db, title="theirs", source="system", author_member_id=theirs.id)

    my_inbox = db.scalars(select(Question).where(Question.author_member_id == mine.id)).all()
    assert [q.title for q in my_inbox] == ["mine"]


def test_backfill_question_authorship_assigns_default_member(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(
        db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True)
    )

    seed = db_module.SessionLocal()
    seed.add(Question(title="legacy question", source="system"))  # pre-migration shape
    seed.commit()
    seed.close()

    db_module._backfill_question_authorship()

    check = db_module.SessionLocal()
    try:
        assert check.query(Question).first().author_member_id is not None
        assert check.query(Member).count() == 1
    finally:
        check.close()

    # Idempotent.
    db_module._backfill_question_authorship()
    check2 = db_module.SessionLocal()
    try:
        assert check2.query(Member).count() == 1
    finally:
        check2.close()


def test_backfill_question_authorship_noop_when_no_questions(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(
        db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True)
    )

    db_module._backfill_question_authorship()

    check = db_module.SessionLocal()
    try:
        assert check.query(Member).count() == 0
    finally:
        check.close()
