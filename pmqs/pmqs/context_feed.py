"""context_feed.py — the unified context-feed (Phase 3).

ONE mechanism that assembles active durable outcomes (Policies, Documents, Meeting
agendas) into a single context block, injected into agent prompts (war-room + 8-lens).
This is what makes PMQs "eat its own cooking": a Policy the PM records becomes standing
context that shapes future agent behavior — the "Memory"-like mechanism from
product-design.md.

Design (product-owner resolved):
- Q1: include ALL ACTIVE durable outcomes, newest-first, capped by a char budget.
  No per-session LLM relevance call (cost-bounded).
- Q3: Policies are GLOBAL and always included; they are placed FIRST and truncated last
  so standing rules are never dropped.
- Q6: char budget is configurable in Settings (default 4000).

Same plumbing for every non-Issue durable type — no per-type bespoke integration.
Never raises: a failure returns an empty block so prompts are simply un-augmented.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import repository, settings
from pmqs.outcomes.types import context_text

log = logging.getLogger(__name__)

_HEADERS = {
    "policy": "STANDING POLICIES",
    "document": "REFERENCE DOCUMENTS",
    "meeting": "MEETING AGENDAS",
}
# Policies first so they survive truncation; then documents, then meetings.
_ORDER = ["policy", "document", "meeting"]


def build_context_block(db: OrmSession, *, char_budget: int | None = None) -> str:
    """Assemble active durable outcomes into a single context block string.

    Returns "" when nothing is active (callers then add nothing to the prompt).
    """
    try:
        budget = char_budget if char_budget is not None else settings.get_context_budget(db)
        outcomes = repository.list_durable_outcomes(db, active_only=True)  # newest-first
        if not outcomes:
            return ""

        # Group by type, preserving newest-first order within each group.
        by_type: dict[str, list[str]] = {"policy": [], "document": [], "meeting": []}
        for o in outcomes:
            text = context_text(o.type, repository.outcome_payload(o)).strip()
            if text:
                by_type.setdefault(o.type, []).append(text)

        sections: list[str] = []
        for otype in _ORDER:
            items = by_type.get(otype) or []
            if not items:
                continue
            body = "\n".join(f"- {t}" for t in items)
            sections.append(f"{_HEADERS[otype]}:\n{body}")

        if not sections:
            return ""

        block = (
            "The following durable context was recorded by the PM in prior sessions. "
            "Treat POLICIES as standing rules you must respect.\n\n"
            + "\n\n".join(sections)
        )
        # Policies-first truncation: sections are already ordered policy→doc→meeting, so a
        # simple tail-truncation drops meetings/documents before policies.
        if len(block) > budget:
            block = block[:budget].rstrip() + "\n…[context truncated]"
        return block
    except Exception as exc:
        log.warning("context_feed assembly failed, returning empty: %s", exc)
        return ""


def augment(base_prompt: str, block: str) -> str:
    """Prepend the context block to a prompt. Returns base unchanged when block empty."""
    if not block:
        return base_prompt
    return f"{block}\n\n---\n\n{base_prompt}"
