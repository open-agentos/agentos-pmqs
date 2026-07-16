"""Tests for prior-outcome retrieval (Shared Outcomes build-spec §10.2, Wave 2 item 8)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products, repository, retrieval
from pmqs.db import Base
from pmqs.models import Member

NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def me(db):
    return members.get_or_create_default_member(db)


@pytest.fixture
def product(db, me):
    return products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _outcome(db, product, *, type="document", payload=None, days_ago=0, lens=None,
             visibility="shared", author=None, retired=False):
    """An outcome, optionally reached from a room whose question carries `lens`."""
    session_id = None
    if lens is not None or visibility == "private":
        q = repository.create_question(db, title="origin", source="system",
                                       lens_tags=[lens] if lens else [], product_id=product.id)
        s = repository.open_session(db, topic="origin", question_id=q.id, product_id=product.id,
                                    author_member_id=(author.id if author else None),
                                    visibility=visibility)
        session_id = s.id
    o = repository.create_outcome(
        db, type=type, payload=payload or {"title": "T", "body": "body text"},
        session_id=session_id, product_id=product.id,
        author_member_id=(author.id if author else None),
    )
    o.created_at = _at(days_ago)
    if retired:
        o.retired_at = _at(0)
    db.commit()
    return o


def _select(db, product, **kw):
    kw.setdefault("token_budget", 10000)
    return retrieval.select_prior_outcomes(db, product_id=product.id, now=NOW, **kw)


# --- filtering ---

def test_retired_outcomes_are_never_returned(db, product, me):
    """§10.2: filter retired_at IS NULL. A retired decision is not a decision."""
    live = _outcome(db, product, payload={"title": "live", "body": "b"})
    _outcome(db, product, payload={"title": "dead", "body": "b"}, retired=True)

    assert [o.id for o in _select(db, product, member_id=me.id)] == [live.id]


def test_another_members_private_outcome_is_not_returned(db, product, me):
    """§10.2: visible per §4. Retrieval must not become a side channel around the
    visibility rules the ledger enforces."""
    colleague = Member(display_name="Ada")
    db.add(colleague)
    db.commit()
    _outcome(db, product, payload={"title": "secret", "body": "b"},
             visibility="private", author=colleague)

    assert _select(db, product, member_id=me.id) == []


def test_does_not_cross_the_product_boundary(db, me):
    a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    mine = _outcome(db, a, payload={"title": "mine", "body": "b"})
    _outcome(db, b, payload={"title": "theirs", "body": "b"})

    assert [o.id for o in _select(db, a, member_id=me.id)] == [mine.id]


def test_empty_product_returns_nothing(db, product, me):
    assert _select(db, product, member_id=me.id) == []


# --- policies bypass ranking ---

def test_policies_are_returned_even_when_old_and_off_lens(db, product, me):
    """"Policies bypass ranking and are always injected" -- that is what "standing rule"
    means. An ancient, unrelated policy still binds."""
    ancient = _outcome(db, product, type="policy",
                       payload={"text": "never ship on a Friday"}, days_ago=3000)
    fresh_doc = _outcome(db, product, type="document",
                         payload={"title": "fresh", "body": "b"}, days_ago=0)

    got = [o.id for o in _select(db, product, member_id=me.id, lens="risk_exposure")]
    assert ancient.id in got
    assert got[0] == ancient.id  # policies first
    assert fresh_doc.id in got


def test_policies_are_kept_when_the_budget_is_tight(db, product, me):
    """Subject to the same budget, but the last thing dropped."""
    _outcome(db, product, type="policy", payload={"text": "KEEP THIS RULE"}, days_ago=1)
    _outcome(db, product, type="document",
             payload={"title": "big", "body": "x" * 4000}, days_ago=0)

    got = _select(db, product, member_id=me.id, token_budget=20)
    assert [o.type for o in got] == ["policy"]


def test_newest_policy_survives_a_budget_squeeze(db, product, me):
    old = _outcome(db, product, type="policy", payload={"text": "o" * 200}, days_ago=500)
    new = _outcome(db, product, type="policy", payload={"text": "n" * 200}, days_ago=1)

    got = [o.id for o in _select(db, product, member_id=me.id, token_budget=55)]
    assert new.id in got
    assert old.id not in got


def test_a_retired_policy_bypasses_nothing(db, product, me):
    """Bypassing ranking is not bypassing the retired filter."""
    _outcome(db, product, type="policy", payload={"text": "withdrawn"}, retired=True)
    assert _select(db, product, member_id=me.id) == []


# --- ranking ---

def test_lens_match_outranks_off_lens(db, product, me):
    off = _outcome(db, product, payload={"title": "off", "body": "b"},
                   lens="growth_adoption", days_ago=0)
    on = _outcome(db, product, payload={"title": "on", "body": "b"},
                  lens="unit_economics", days_ago=0)

    got = [o.id for o in _select(db, product, member_id=me.id, lens="unit_economics")]
    assert got.index(on.id) < got.index(off.id)


def test_recent_outranks_old_at_equal_affinity(db, product, me):
    old = _outcome(db, product, payload={"title": "old", "body": "b"},
                   lens="unit_economics", days_ago=900)
    new = _outcome(db, product, payload={"title": "new", "body": "b"},
                   lens="unit_economics", days_ago=1)

    got = [o.id for o in _select(db, product, member_id=me.id, lens="unit_economics")]
    assert got.index(new.id) < got.index(old.id)


def test_recency_is_a_decay_not_a_cutoff(db, product, me):
    """An old decision still surfaces when nothing newer competes -- otherwise the ledger
    silently forgets, which is the opposite of the point."""
    old = _outcome(db, product, payload={"title": "old", "body": "b"}, days_ago=2000)
    assert [o.id for o in _select(db, product, member_id=me.id)] == [old.id]


def test_type_weight_breaks_ties(db, product, me):
    """A document informs a new question more than a meeting agenda does."""
    meeting = _outcome(db, product, type="meeting",
                       payload={"title": "m", "agenda": "b"}, days_ago=0)
    document = _outcome(db, product, type="document",
                        payload={"title": "d", "body": "b"}, days_ago=0)

    got = [o.id for o in _select(db, product, member_id=me.id)]
    assert got.index(document.id) < got.index(meeting.id)


def test_topic_overlap_lifts_an_untagged_outcome(db, product, me):
    """§10.2 names `topic` in the signature but omits it from the formula; this is the
    documented reading -- wording is weak evidence of relevance."""
    unrelated = _outcome(db, product, payload={"title": "unrelated", "body": "kittens"}, days_ago=0)
    related = _outcome(db, product,
                       payload={"title": "pricing", "body": "enterprise pricing tiers"}, days_ago=0)

    got = [o.id for o in _select(db, product, member_id=me.id, topic="enterprise pricing tiers")]
    assert got.index(related.id) < got.index(unrelated.id)


def test_off_lens_outcomes_are_deprioritised_not_hidden(db, product, me):
    """Cross-lens precedent is often the most useful kind. The affinity floor is
    non-zero so budget headroom still surfaces it."""
    off = _outcome(db, product, payload={"title": "off", "body": "b"},
                   lens="growth_adoption", days_ago=0)

    assert [o.id for o in _select(db, product, member_id=me.id, lens="unit_economics")] == [off.id]


# --- token budget ---

def test_capped_by_token_budget_not_row_count(db, product, me):
    """A row cap looks like a bound and isn't. Twenty one-line policies and twenty
    5,000-word documents are the same row count and wildly different prompts."""
    for i in range(10):
        _outcome(db, product, payload={"title": f"doc{i}", "body": "x" * 400}, days_ago=i)

    got = _select(db, product, member_id=me.id, token_budget=120)
    total = sum(retrieval.estimate_tokens(
        retrieval.context_text(o.type, repository.outcome_payload(o))) for o in got)
    assert total <= 120
    assert 0 < len(got) < 10


def test_zero_budget_returns_nothing(db, product, me):
    _outcome(db, product, type="policy", payload={"text": "a rule"})
    assert _select(db, product, member_id=me.id, token_budget=0) == []


def test_the_ledger_is_never_dumped_wholesale(db, product, me):
    """§10.2's blunt instruction: "Do not dump the ledger into the prompt."."""
    for i in range(50):
        _outcome(db, product, payload={"title": f"doc{i}", "body": "x" * 1000}, days_ago=i)

    got = _select(db, product, member_id=me.id, token_budget=500)
    assert len(got) < 50


# --- resilience ---

def test_bad_timestamp_does_not_raise(db, product, me):
    o = _outcome(db, product, payload={"title": "t", "body": "b"})
    o.created_at = "not-a-timestamp"
    db.commit()
    assert [x.id for x in _select(db, product, member_id=me.id)] == [o.id]


def test_retrieval_failure_returns_empty_not_raises(db, product, me, monkeypatch):
    """This feeds prompts: an un-augmented prompt is a worse answer, an exception is no
    answer at all."""
    monkeypatch.setattr(repository, "list_ledger_outcomes",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert _select(db, product, member_id=me.id) == []
