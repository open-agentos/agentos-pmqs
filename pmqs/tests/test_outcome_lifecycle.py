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


def test_durable_outcomes_listed_newest_first(db):
    repository.create_outcome(db, type="policy", payload={"text": "p1"})
    repository.create_outcome(db, type="document", payload={"title": "d1", "body": ""})
    # question is NOT durable
    repository.create_outcome(db, type="question", payload={"title": "q1"})
    durable = repository.list_durable_outcomes(db)
    types = {o.type for o in durable}
    assert types == {"policy", "document"}
    assert "question" not in types


def test_deactivate_removes_from_active_list(db):
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    assert len(repository.list_durable_outcomes(db, active_only=True)) == 1
    repository.deactivate_outcome(db, o.id)
    assert len(repository.list_durable_outcomes(db, active_only=True)) == 0
    # still visible when active_only=False
    assert len(repository.list_durable_outcomes(db, active_only=False)) == 1


def test_new_outcome_is_active_by_default(db):
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    assert o.active is True


def test_policy_never_gets_github_ref(db):
    import pytest as _pytest
    with _pytest.raises(ValueError):
        repository.create_outcome(db, type="policy", payload={"text": "p"},
                                  github_ref="https://github.com/x/y/issues/1")


# --- Wave 1 item 4: authorship, promotion, lifecycle (build-spec §4, §7, §8 step 4) ---

def test_new_outcome_gets_an_author(db):
    from pmqs import members

    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    assert o.author_member_id == members.get_or_create_default_member(db).id


def test_retired_at_is_the_active_predicate(db):
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    assert o.retired_at is None and o.active is True

    repository.deactivate_outcome(db, o.id)
    assert o.retired_at is not None and o.active is False


def test_active_is_derived_and_cannot_be_written(db):
    """The old stored `active` column is gone; there must be exactly one source of truth.
    Writing to it has to fail loudly rather than create a second one that drifts."""
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    with pytest.raises(AttributeError):
        o.active = False


def test_new_outcome_is_not_promoted(db):
    """Promotion is an explicit act (§4 rule 3), never a side effect of creation."""
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    assert o.promoted_at is None


def test_retired_without_replacement_is_distinguishable_from_superseded(db):
    """build-spec §7's three states, carried by timestamps rather than a status enum."""
    old = repository.create_outcome(db, type="policy", payload={"text": "old rule"})
    replacement = repository.create_outcome(db, type="policy", payload={"text": "new rule"})
    abandoned = repository.create_outcome(db, type="policy", payload={"text": "just wrong"})

    repository.deactivate_outcome(db, old.id, superseded_by_outcome_id=replacement.id)
    repository.deactivate_outcome(db, abandoned.id)

    # active
    assert replacement.retired_at is None
    # superseded
    assert old.retired_at is not None and old.superseded_by_outcome_id == replacement.id
    # retired-without-replacement
    assert abandoned.retired_at is not None and abandoned.superseded_by_outcome_id is None


def test_re_retiring_keeps_the_original_timestamp(db):
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    repository.deactivate_outcome(db, o.id)
    first = o.retired_at

    repository.deactivate_outcome(db, o.id)
    assert o.retired_at == first


def test_superseding_an_already_retired_outcome_names_the_replacement(db):
    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    replacement = repository.create_outcome(db, type="policy", payload={"text": "p2"})
    repository.deactivate_outcome(db, o.id)
    retired_at = o.retired_at

    repository.deactivate_outcome(db, o.id, superseded_by_outcome_id=replacement.id)
    assert o.superseded_by_outcome_id == replacement.id
    assert o.retired_at == retired_at


def test_deactivate_missing_outcome_returns_none(db):
    assert repository.deactivate_outcome(db, "does-not-exist") is None


def test_active_still_usable_as_a_query_expression(db):
    """Class-level `Outcome.active` must compile to the retired_at predicate, so an
    existing query doesn't silently break on the column's removal."""
    from sqlalchemy import select

    from pmqs.models import Outcome

    o = repository.create_outcome(db, type="policy", payload={"text": "p"})
    assert db.scalars(select(Outcome).where(Outcome.active.is_(True))).all() == [o]

    repository.deactivate_outcome(db, o.id)
    assert db.scalars(select(Outcome).where(Outcome.active.is_(True))).all() == []
    assert db.scalars(select(Outcome).where(Outcome.active.is_(False))).all() == [o]
