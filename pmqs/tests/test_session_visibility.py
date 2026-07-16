"""Tests for Session authorship + visibility (Shared Outcomes build-spec, Wave 1
item 3 / build-spec §4, §7, §8 step 3)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, repository
from pmqs.db import Base
from pmqs.models import Member


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    yield session
    session.close()


def test_new_session_defaults_to_shared_visibility(db):
    sess = repository.open_session(db, topic="Ship or wait?")
    assert sess.visibility == "shared"


def test_new_session_gets_an_author(db):
    sess = repository.open_session(db, topic="Ship or wait?")
    assert sess.author_member_id is not None
    member = members.get_or_create_default_member(db)
    assert sess.author_member_id == member.id


def test_session_can_be_created_private(db):
    sess = repository.open_session(db, topic="A private matter", visibility="private")
    assert sess.visibility == "private"


def test_private_session_retrievable_only_by_its_author(db):
    author = members.get_or_create_default_member(db)
    other = Member(display_name="Someone else")
    db.add(other)
    db.commit()

    sess = repository.open_session(db, topic="private topic", visibility="private", author_member_id=author.id)

    assert repository.get_visible_session_row(db, sess.id, member_id=author.id) is not None
    assert repository.get_visible_session_row(db, sess.id, member_id=other.id) is None
    assert repository.get_visible_session_row(db, sess.id, member_id=None) is None


def test_shared_session_retrievable_by_anyone(db):
    author = members.get_or_create_default_member(db)
    other = Member(display_name="Someone else")
    db.add(other)
    db.commit()

    sess = repository.open_session(db, topic="shared topic", author_member_id=author.id)

    assert repository.get_visible_session_row(db, sess.id, member_id=author.id) is not None
    assert repository.get_visible_session_row(db, sess.id, member_id=other.id) is not None


def test_get_visible_session_row_returns_none_for_missing_session(db):
    assert repository.get_visible_session_row(db, "does-not-exist", member_id=None) is None
