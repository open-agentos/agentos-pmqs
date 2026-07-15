"""position_doc.py — on-demand Voter-Guide Position Document generator (Phase 2 task 3).

Voter Guide format (product-design.md):
  1. Plain-language summary
  2. "What your vote means" — yes/no consequence framing
  3. Neutral analyst background / cost-impact section
  4. Argument FOR + rebuttal
  5. Argument AGAINST + rebuttal

Generated ONCE, on demand, persisted indefinitely (no regenerate) — see the caller in
api/workspace.py which no-ops if session.position_doc is already set. LLM failure
returns a clearly-marked fallback doc rather than crashing.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import llm, settings

log = logging.getLogger(__name__)

# Explicit schema so the doc always has the five Voter-Guide sections.
SECTIONS = ("summary", "what_your_vote_means", "background_impact",
            "argument_for", "rebuttal_for", "argument_against", "rebuttal_against")

_SYSTEM = (
    "You produce a decision briefing in the California Voter Guide format for a product "
    "manager, grounded strictly in the provided evidence. Be neutral and thorough. "
    "Respond as JSON with EXACTLY these keys: summary (plain-language), "
    "what_your_vote_means (yes/no consequence framing), background_impact (neutral "
    "analyst background + cost/impact), argument_for, rebuttal_for, argument_against, "
    "rebuttal_against. No markdown."
)


def _fallback(question: Any) -> dict[str, Any]:
    ev = getattr(question, "evidence_list", None) or getattr(question, "evidence", []) or []
    note = "[LLM unavailable — Position Document could not be generated. Check Settings.]"
    return {
        "summary": note,
        "what_your_vote_means": note,
        "background_impact": note,
        "argument_for": note,
        "rebuttal_for": note,
        "argument_against": note,
        "rebuttal_against": note,
        "evidence": ev,
        "degraded": True,
    }


def generate(db: OrmSession, question: Any) -> dict[str, Any]:
    """Generate the Voter-Guide Position Document for a Question. Never raises for LLM."""
    ev = getattr(question, "evidence_list", None) or getattr(question, "evidence", []) or []
    if not llm.is_enabled():
        return _fallback(question)

    user = (
        f"Decision/question: {getattr(question, 'title', '')}\n"
        f"Detail: {getattr(question, 'description', '') or ''}\n"
        f"Evidence: {ev}"
    )
    try:
        result = llm.complete_json(_SYSTEM, user, settings_cfg=settings.get_llm(db), max_tokens=1200)
        if not isinstance(result, dict):
            return _fallback(question)
        # Ensure all sections exist (fill missing with empty string).
        doc: dict[str, Any] = {k: str(result.get(k, "")) for k in SECTIONS}
        doc["evidence"] = ev
        doc["degraded"] = False
        return doc
    except Exception as exc:
        log.warning("position doc generation failed: %s", exc)
        return _fallback(question)
