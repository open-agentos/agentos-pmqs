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


def test_position_doc_uses_generous_token_budget(db, monkeypatch):
    # All 7 sections share one call; a tight budget forces uniform thinness. Pin that the
    # generator asks for real room (and that it's the env-tunable constant, not a literal).
    captured = {}
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: True)

    def cap(s, u, **k):
        captured.update(k)
        return {k2: f"text for {k2}" for k2 in SECTIONS}

    monkeypatch.setattr(position_doc.llm, "complete_json", cap)
    position_doc.generate(db, _q(db))
    assert captured["max_tokens"] == position_doc._MAX_TOKENS
    assert captured["max_tokens"] >= 4000


def test_position_doc_model_override(db, monkeypatch):
    # PMQS_POSITION_DOC_MODEL swaps the model for this premium artifact while leaving the
    # rest of the operator's LLM settings (provider/base_url/key) intact.
    captured = {}
    monkeypatch.setenv("PMQS_POSITION_DOC_MODEL", "anthropic/claude-sonnet-4.5")
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: True)

    def cap(s, u, **k):
        captured.update(k)
        return {k2: "x" for k2 in SECTIONS}

    monkeypatch.setattr(position_doc.llm, "complete_json", cap)
    position_doc.generate(db, _q(db))
    assert captured["settings_cfg"]["model"] == "anthropic/claude-sonnet-4.5"
