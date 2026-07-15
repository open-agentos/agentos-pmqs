from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, context_feed


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_empty_when_no_durable_outcomes(db):
    assert context_feed.build_context_block(db) == ""


def test_block_includes_active_policy(db):
    repository.create_outcome(db, type="policy", payload={"text": "cap retries at 3"})
    block = context_feed.build_context_block(db)
    assert "STANDING POLICIES" in block
    assert "cap retries at 3" in block


def test_deactivated_outcome_excluded(db):
    o = repository.create_outcome(db, type="policy", payload={"text": "old rule"})
    repository.deactivate_outcome(db, o.id)
    assert context_feed.build_context_block(db) == ""


def test_question_and_issue_not_in_feed(db):
    repository.create_outcome(db, type="question", payload={"title": "q"})
    repository.create_outcome(db, type="issue", payload={"title": "i"}, github_ref="http://x")
    assert context_feed.build_context_block(db) == ""


def test_policies_survive_truncation(db):
    # A long document plus a short policy, with a tiny budget → policy must remain.
    repository.create_outcome(db, type="document", payload={"title": "Big", "body": "x" * 5000})
    repository.create_outcome(db, type="policy", payload={"text": "KEEP THIS POLICY"})
    block = context_feed.build_context_block(db, char_budget=200)
    assert "KEEP THIS POLICY" in block            # policy first, never dropped
    assert "truncated" in block                     # document body got cut
    assert len(block) <= 240                         # budget + truncation marker


def test_augment_prepends_block(db):
    assert context_feed.augment("PROMPT", "") == "PROMPT"
    out = context_feed.augment("PROMPT", "BLOCK")
    assert out.startswith("BLOCK")
    assert "PROMPT" in out


def test_no_policy_text_ever_bound_to_github(db):
    # Reassert the hard rule at the feed layer: policies are context, never GitHub payload.
    repository.create_outcome(db, type="policy", payload={"text": "secret policy"})
    block = context_feed.build_context_block(db)
    # The feed is for prompts only; it must not fabricate github refs.
    assert "github" not in block.lower()
