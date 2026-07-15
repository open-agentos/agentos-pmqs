"""framing.py — LLM framing pass (Phase 1 task 2). STUBBED.

Runs AFTER a structural trigger fires, as a separate step. Takes a trigger's raw hit
and produces a human-readable title/description. Decoupled from the trigger so the
trigger stays deterministic/swappable.

Phase 1 status: STUBBED. The LLM call is not wired (per build decision). The stub
produces a deterministic, non-empty title/description from the hit so the pipeline
runs end to end. A real LiteLLM call slots into `_call_llm` later. Critically: an LLM
failure must NOT crash the trigger pipeline — the fallback below guarantees a
Question still gets a usable title/description.
"""
from __future__ import annotations

from typing import Any


def _call_llm(hit: dict[str, Any]) -> dict[str, str] | None:
    """Real LLM framing goes here (LiteLLM). Returns None while stubbed."""
    return None  # STUB: not wired yet.


def _fallback(hit: dict[str, Any]) -> dict[str, str]:
    ref = hit.get("ref", "")
    reason = hit.get("reason", "flagged by a structural trigger")
    title = hit.get("title") or f"Review {ref}: {reason}"
    desc = (
        f"[auto-framed / LLM stub]\n"
        f"Trigger: {hit.get('trigger', 'unknown')}\n"
        f"Reason: {reason}\n"
        f"Reference: {ref}"
    )
    return {"title": title[:200], "description": desc}


def frame(hit: dict[str, Any]) -> dict[str, str]:
    """Produce {title, description} for a trigger hit. Never raises."""
    try:
        result = _call_llm(hit)
    except Exception:
        result = None
    if result and result.get("title") and result.get("description"):
        return result
    return _fallback(hit)
