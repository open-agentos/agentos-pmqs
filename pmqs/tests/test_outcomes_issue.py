"""test_outcomes_issue.py — Issue outcome writes a row + promotes the Question.

Uses a fake AgentOSClient so the test does NOT hit real GitHub. The live round-trip
against agentos-pmqs is verified manually (see build report), per the Phase 1
acceptance criterion.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs.db import Base
from pmqs import repository
from pmqs.outcomes.issue import push_question_to_issue


class FakeClient:
    def __init__(self):
        self.calls = []

    def create_issue(self, title, body, labels=None):
        self.calls.append((title, body, labels))
        return {"url": "https://github.com/open-agentos/agentos-pmqs/issues/999", "number": 999}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = Session()
    yield s
    s.close()


def test_push_creates_outcome_and_promotes(db):
    q = repository.create_question(
        db, title="Push me", source="system", description="body",
        lens_tags=["risk_exposure"], evidence=[{"type": "issue", "ref": "#47", "url": "u"}],
    )
    result = push_question_to_issue(db, q, client=FakeClient())

    assert result["number"] == 999
    assert "issues/999" in result["github_ref"]

    outcomes = repository.list_outcomes(db)
    assert len(outcomes) == 1
    assert outcomes[0].type == "issue"
    assert outcomes[0].github_ref == result["github_ref"]

    refreshed = repository.get_question(db, q.id)
    assert refreshed.status == "promoted"


def test_policy_outcome_never_gets_github_ref(db):
    with pytest.raises(ValueError):
        repository.create_outcome(db, type="policy", payload={"text": "x"},
                                  github_ref="https://github.com/should/not/happen")
    # policy without github_ref is fine
    o = repository.create_outcome(db, type="policy", payload={"text": "x"})
    assert o.github_ref is None


def test_question_persists_across_sessions():
    # Phase 0.5 exit criterion: survives a "restart" (new session, same file DB).
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{path}", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        s1 = Session()
        q = repository.create_question(s1, title="persist", source="pm")
        qid = q.id
        s1.close()
        # new session simulates restart
        s2 = Session()
        again = repository.get_question(s2, qid)
        assert again is not None and again.title == "persist"
        s2.close()
    finally:
        os.remove(path)
