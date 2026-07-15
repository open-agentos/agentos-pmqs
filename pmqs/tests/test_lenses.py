from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, lenses, scoring


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def _session_with_q(db):
    q = repository.create_question(db, title="Mitigate #47 or wait?", source="system",
                                   evidence=[{"type": "issue", "ref": "#47", "url": "u"}])
    return repository.open_session(db, topic="Mitigate #47 or wait?", question_id=q.id)


def test_run_lenses_persists_scored_proposed_questions(db, monkeypatch):
    monkeypatch.setattr(lenses.llm, "is_enabled", lambda: True)
    # triage returns 2 lenses; each generates a distinct candidate
    def fake_json(system, user, **kw):
        if "triage" in system.lower() or "which" in system.lower() or "lenses" in system.lower():
            return {"lenses": ["risk_exposure", "quality_reliability"]}
        # generation call — vary by lens in the user prompt
        if "risk_exposure" in user:
            return {"title": "Risk: partial fix leaves upgrade unsafe", "description": "d1"}
        return {"title": "Quality: mitigation masks root cause", "description": "d2"}
    monkeypatch.setattr(lenses.llm, "complete_json", fake_json)

    sess = _session_with_q(db)
    qs = lenses.run_session_lenses(db, sess)
    # Both lens-questions share the originating evidence (#47), so dedup merges them
    # into one surviving Question with unioned lens tags — correct product behavior
    # (same underlying issue, different angles).
    assert len(qs) == 1
    survivor = qs[0]
    assert set(survivor.lens_tags_list) == {"risk_exposure", "quality_reliability"}
    assert survivor.status == "proposed"
    assert survivor.source == "system"
    assert survivor.score is not None
    expected_score, _ = scoring.score_question(survivor)
    assert abs(survivor.score - expected_score) < 1e-9


def test_run_lenses_empty_when_llm_off(db, monkeypatch):
    monkeypatch.setattr(lenses.llm, "is_enabled", lambda: False)
    sess = _session_with_q(db)
    assert lenses.run_session_lenses(db, sess) == []


def test_run_lenses_survives_triage_failure(db, monkeypatch):
    monkeypatch.setattr(lenses.llm, "is_enabled", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(lenses.llm, "complete_json", boom)
    sess = _session_with_q(db)
    assert lenses.run_session_lenses(db, sess) == []  # no crash, no candidates
