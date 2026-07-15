"""test_llm.py — framing/dedup behave correctly with LLM OFF (deterministic fallback),
and the LLM seam is honoured when a stub 'LLM' is injected.
"""
import os

import pmqs.framing as framing
import pmqs.dedup as dedup


def test_framing_falls_back_when_llm_off(monkeypatch):
    monkeypatch.setenv("PMQS_LLM_MODE", "off")
    hit = {"trigger": "stale_issue_age", "lens_tags": ["quality_reliability"],
           "ref": "#42", "reason": "open 30d", "title": "Stale #42"}
    out = framing.frame(hit)
    assert out["title"] and out["description"]
    assert "LLM stub" in out["description"] or "auto-framed" in out["description"]


def test_framing_uses_llm_when_available(monkeypatch):
    monkeypatch.setattr(framing.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(
        framing.llm, "complete_json",
        lambda system, user, **kw: {"title": "LLM title", "description": "LLM desc"},
    )
    out = framing.frame({"trigger": "t", "lens_tags": [], "ref": "#1", "reason": "r"})
    assert out == {"title": "LLM title", "description": "LLM desc"}


def test_framing_survives_llm_exception(monkeypatch):
    monkeypatch.setattr(framing.llm, "is_enabled", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(framing.llm, "complete_json", boom)
    out = framing.frame({"trigger": "t", "lens_tags": [], "ref": "#1", "reason": "r"})
    assert out["title"] and out["description"]  # fell back, did not crash


def test_dedup_uses_llm_verdict(monkeypatch):
    monkeypatch.setattr(dedup.llm, "is_enabled", lambda: True)
    # Force LLM to say "duplicate" even for lexically distinct titles.
    monkeypatch.setattr(dedup.llm, "complete_json", lambda s, u, **k: {"duplicate": True})
    cands = [
        {"title": "alpha unique words", "description": "a", "lens_tags": [], "evidence": [{"ref": "#1"}], "source": "system"},
        {"title": "beta different words", "description": "b", "lens_tags": [], "evidence": [{"ref": "#2"}], "source": "system"},
    ]
    assert len(dedup.dedup(cands)) == 1


def test_dedup_heuristic_when_llm_off(monkeypatch):
    monkeypatch.setenv("PMQS_LLM_MODE", "off")
    cands = [
        {"title": "totally distinct one", "description": "a", "lens_tags": [], "evidence": [{"ref": "#1"}], "source": "system"},
        {"title": "completely separate two", "description": "b", "lens_tags": [], "evidence": [{"ref": "#2"}], "source": "system"},
    ]
    assert len(dedup.dedup(cands)) == 2
