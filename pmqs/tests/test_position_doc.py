from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, position_doc
from pmqs.position_doc import SECTIONS


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def _q(db):
    return repository.create_question(
        db, title="Mitigate #47 or wait?", source="system", description="detail",
        evidence=[{"type": "issue", "ref": "#47", "url": "u"}],
    )


def test_generate_has_all_voter_guide_sections(db, monkeypatch):
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(
        position_doc.llm, "complete_json",
        lambda s, u, **k: {k2: f"text for {k2}" for k2 in SECTIONS},
    )
    doc = position_doc.generate(db, _q(db))
    for section in SECTIONS:
        assert doc[section] and doc[section] != ""
    assert doc["degraded"] is False
    # evidence carried through
    assert doc["evidence"][0]["ref"] == "#47"


def test_generate_fallback_on_llm_failure(db, monkeypatch):
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(position_doc.llm, "complete_json", boom)
    doc = position_doc.generate(db, _q(db))
    assert doc["degraded"] is True
    assert all(section in doc for section in SECTIONS)  # structure intact, no crash


def test_generate_llm_off(db, monkeypatch):
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: False)
    doc = position_doc.generate(db, _q(db))
    assert doc["degraded"] is True
