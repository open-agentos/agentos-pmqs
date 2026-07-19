"""test_outcome_draft.py — drafting an outcome from session context (Wave 2).

LLM forced off, so these exercise the graceful-fallback path: every type returns an
editable stub with the right field set and never raises. The live-LLM path is verified
manually (same discipline as position_doc / warroom).
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs.db import Base
from pmqs import repository
from pmqs.outcomes.draft import DRAFT_FIELDS, generate_draft


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.mark.parametrize("otype", sorted(DRAFT_FIELDS))
def test_each_type_returns_its_field_set(db, otype):
    sess = repository.open_session(db, topic="Ship or wait on #47")
    out = generate_draft(db, sess, otype)
    assert out["type"] == otype
    assert set(out["fields"].keys()) == set(DRAFT_FIELDS[otype])
    # LLM off → degraded stub, but still usable/editable.
    assert out["degraded"] is True


def test_fallback_seeds_title_with_topic(db):
    sess = repository.open_session(db, topic="Cut the retry budget")
    out = generate_draft(db, sess, "document")
    assert out["fields"]["title"] == "Cut the retry budget"
    # the body carries the write-it-yourself note, never empty
    assert out["fields"]["body"].strip()


def test_policy_fallback_has_text_field_only(db):
    sess = repository.open_session(db, topic="whatever")
    out = generate_draft(db, sess, "policy")
    assert list(out["fields"].keys()) == ["text"]
    assert out["fields"]["text"].strip()  # never a blank rule


def test_unknown_type_raises(db):
    sess = repository.open_session(db, topic="x")
    with pytest.raises(ValueError):
        generate_draft(db, sess, "banana")


def test_draft_never_raises_even_with_a_broken_position_doc(db):
    # A malformed position_doc blob must not sink the draft (fail open).
    sess = repository.open_session(db, topic="robust")
    sess.position_doc = "{not valid json"
    db.commit()
    out = generate_draft(db, sess, "issue")
    assert out["type"] == "issue" and out["degraded"] is True
