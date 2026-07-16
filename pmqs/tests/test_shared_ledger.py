"""Tests for the Product-scoped Outcomes ledger, §4 visibility resolution, the promote
action, and the member-scoped Inbox (Shared Outcomes build-spec, Wave 2 item 5).

The load-bearing pair here: the ledger is Product-wide (a colleague's outcomes are the
whole point) while the Inbox stays member-private. Wave 2 item 5's acceptance calls out
the second half explicitly -- "Inbox reads remain member-scoped -- assert this with a
test" -- because widening the ledger is exactly the change most likely to widen the inbox
by accident.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products, repository
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
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    yield session
    session.close()


@pytest.fixture
def product(db):
    return products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")


@pytest.fixture
def me(db):
    return members.get_or_create_default_member(db)


@pytest.fixture
def colleague(db):
    m = Member(display_name="A colleague")
    db.add(m)
    db.commit()
    return m


def _outcome_in(db, product, author, *, visibility="shared", type="policy"):
    session = repository.open_session(
        db, topic="a question", product_id=product.id,
        author_member_id=author.id, visibility=visibility,
    )
    return repository.create_outcome(
        db, type=type, payload={"text": f"{visibility} outcome"},
        session_id=session.id, product_id=product.id, author_member_id=author.id,
    )


# --- §4 visibility resolution ---

def test_outcome_in_a_shared_room_is_shared(db, product, colleague):
    o = _outcome_in(db, product, colleague, visibility="shared")
    assert repository.outcome_is_shared(db, o) is True


def test_outcome_in_a_private_room_is_not_shared(db, product, colleague):
    o = _outcome_in(db, product, colleague, visibility="private")
    assert repository.outcome_is_shared(db, o) is False


def test_outcome_with_no_room_is_shared(db, product, me):
    """Nothing to inherit privacy from, so it follows the room default (§4 rule 1)."""
    o = repository.create_outcome(db, type="policy", payload={"text": "direct"}, product_id=product.id)
    assert repository.outcome_is_shared(db, o) is True


def test_promoted_outcome_is_shared_despite_its_private_room(db, product, colleague):
    o = _outcome_in(db, product, colleague, visibility="private")
    repository.promote_outcome(db, o.id)
    assert repository.outcome_is_shared(db, o) is True


# --- the ledger is Product-scoped, not member-scoped ---

def test_ledger_returns_all_members_outcomes_for_the_product(db, product, me, colleague):
    mine = _outcome_in(db, product, me)
    theirs = _outcome_in(db, product, colleague)

    ledger = repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id)
    assert {o.id for o in ledger} == {mine.id, theirs.id}


def test_ledger_hides_other_members_private_rooms(db, product, me, colleague):
    mine = _outcome_in(db, product, me)
    theirs_private = _outcome_in(db, product, colleague, visibility="private")

    ledger = repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id)
    assert {o.id for o in ledger} == {mine.id}
    assert theirs_private.id not in {o.id for o in ledger}


def test_ledger_shows_me_my_own_private_room(db, product, me):
    mine_private = _outcome_in(db, product, me, visibility="private")

    ledger = repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id)
    assert {o.id for o in ledger} == {mine_private.id}


def test_ledger_shows_a_promoted_private_outcome_to_everyone(db, product, me, colleague):
    theirs = _outcome_in(db, product, colleague, visibility="private")
    assert repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id) == []

    repository.promote_outcome(db, theirs.id)

    ledger = repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id)
    assert {o.id for o in ledger} == {theirs.id}


def test_ledger_does_not_cross_the_product_boundary(db, me):
    """§2: the boundary is the Product. Nothing crosses it."""
    a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    in_a = _outcome_in(db, a, me)
    _outcome_in(db, b, me)

    ledger = repository.list_ledger_outcomes(db, product_id=a.id, member_id=me.id)
    assert {o.id for o in ledger} == {in_a.id}


def test_ledger_with_unknown_viewer_shows_no_private_rooms(db, product, colleague):
    """member_id=None must not compile to `author_member_id IS NULL` and expose private
    rooms that predate the authorship backfill."""
    from pmqs.models import Session as SessionModel

    o = _outcome_in(db, product, colleague, visibility="private")
    # Simulate a pre-backfill room: private, no author.
    db.query(SessionModel).filter(SessionModel.id == o.session_id).update({"author_member_id": None})
    db.commit()

    assert repository.list_ledger_outcomes(db, product_id=product.id, member_id=None) == []


def test_ledger_is_newest_first(db, product, me):
    first = _outcome_in(db, product, me)
    second = _outcome_in(db, product, me)
    first.created_at = "2026-01-01T00:00:00+00:00"
    second.created_at = "2026-06-01T00:00:00+00:00"
    db.commit()

    ledger = repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id)
    assert [o.id for o in ledger] == [second.id, first.id]


# --- promote action ---

def test_promote_stamps_promoted_at(db, product, me):
    o = _outcome_in(db, product, me, visibility="private")
    assert o.promoted_at is None

    repository.promote_outcome(db, o.id)
    assert o.promoted_at is not None


def test_promote_is_rejected_on_an_already_shared_outcome(db, product, me):
    o = _outcome_in(db, product, me, visibility="shared")
    with pytest.raises(repository.OutcomeAlreadySharedError):
        repository.promote_outcome(db, o.id)


def test_promote_is_rejected_on_an_already_promoted_outcome(db, product, me):
    """Promotion is one-way (§4 rule 4) -- there is no demote, so a second promote is a
    mistaken caller, not a no-op."""
    o = _outcome_in(db, product, me, visibility="private")
    repository.promote_outcome(db, o.id)
    with pytest.raises(repository.OutcomeAlreadySharedError):
        repository.promote_outcome(db, o.id)


def test_promote_missing_outcome_returns_none(db):
    assert repository.promote_outcome(db, "does-not-exist") is None


def test_there_is_no_demote(db, product, me):
    """§4 rule 4 is a one-way door. If a demote ever appears, this test should be the
    thing that argues with it."""
    assert not hasattr(repository, "demote_outcome")


# --- the Inbox stays private (item 5 acceptance) ---

def test_inbox_reads_remain_member_scoped(db, product, me, colleague):
    repository.create_question(db, title="mine", source="system",
                               product_id=product.id, author_member_id=me.id)
    repository.create_question(db, title="theirs", source="system",
                               product_id=product.id, author_member_id=colleague.id)

    inbox = repository.list_questions(db, product_id=product.id, member_id=me.id)
    assert [q.title for q in inbox] == ["mine"]


def test_inbox_does_not_widen_when_the_ledger_does(db, product, me, colleague):
    """The two halves of the product move in opposite directions and must not be
    accidentally coupled: ledger Product-wide, inbox member-private."""
    _outcome_in(db, product, colleague)
    repository.create_question(db, title="theirs", source="system",
                               product_id=product.id, author_member_id=colleague.id)

    assert len(repository.list_ledger_outcomes(db, product_id=product.id, member_id=me.id)) == 1
    assert repository.list_questions(db, product_id=product.id, member_id=me.id) == []
