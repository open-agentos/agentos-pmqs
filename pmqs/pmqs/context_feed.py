"""context_feed.py — the unified context-feed (Phase 3).

ONE mechanism that assembles active durable outcomes (Policies, Documents, Meeting
agendas) into a single context block, injected into agent prompts (war-room + 8-lens).
This is what makes PMQs "eat its own cooking": a Policy the PM records becomes standing
context that shapes future agent behavior — the "Memory"-like mechanism from
product-design.md.

Design (product-owner resolved):
- Q1: include ALL ACTIVE durable outcomes, newest-first, capped by a char budget.
  No per-session LLM relevance call (cost-bounded).
- Q3: Policies are always included within their Product; they are placed FIRST and
  truncated last so standing rules are never dropped.
- Q6: char budget is configurable in Settings (default 4000).

SCOPE — read before touching (build-spec §5, Wave 2 item 6):
Durable outcomes are PRODUCT-scoped, not member-scoped and not global. Every member of
a Product feeds every other member's agents -- that is Loop 1, the whole network effect
in one query. But nothing crosses the Product boundary (§2).

`product_id` is a REQUIRED keyword. It reads as noise at a call site that "obviously"
has only one product; it is not. Before Wave 2 item 6 this function took no product at
all and returned every product's policies to every product's agents -- a live
cross-product leak, sitting behind a docstring that said "Policies are GLOBAL" as though
that were the design. Making the parameter required is what stops that returning by
omission.

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


def build_context_block(
    db: OrmSession, *, product_id: str | None, char_budget: int | None = None
) -> str:
    """Assemble a Product's active durable outcomes into a single context block string.

    `product_id` scopes the feed and is required -- see SCOPE in the module docstring.
    Passing None explicitly means "unscoped", which is only correct where there is
    genuinely no single product in play; it is not a default to reach for.

    Only ACTIVE outcomes are fed: `retired_at IS NULL` (build-spec §7). A retired policy
    is not a weaker policy, it is not a policy -- and a shared ledger that keeps feeding
    withdrawn standing rules gets dumber as the team gets busier (§12 "landfill").

    Returns "" when nothing is active (callers then add nothing to the prompt).
    """
    try:
        budget = char_budget if char_budget is not None else settings.get_context_budget(db)
        outcomes = repository.list_durable_outcomes(
            db, active_only=True, product_id=product_id
        )  # newest-first
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
