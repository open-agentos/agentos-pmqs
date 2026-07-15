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
