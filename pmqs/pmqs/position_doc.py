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

WAVE 2 ITEM 10 (build-spec §9) — Loop 4. The doc now cites the Product's prior
decisions, with author and date, retrieved via item 8 (retrieval.select_prior_outcomes).

- NO NEW RESEARCH PASS (item 10 acceptance). Retrieval is a DB query against the
  existing ledger, not another LLM round-trip; generate() still makes exactly one LLM
  call, asserted by a test. The whole point of a Product-wide ledger is that the prior
  thinking is already there -- paying to rediscover it would be the joke.
- A PRIOR DECISION CAN APPEAR IN THE *AGAINST* COLUMN (item 10 acceptance). This is the
  §12 groupthink guard again, in the surface where it matters most: the Voter Guide's
  whole value is arguing both sides honestly. If prior decisions could only ever support
  the FOR column, the ledger would stop being a memory and start being a ratchet -- every
  past decision silently reinforcing itself. The system prompt says so explicitly.

Citations carry the AUTHOR because "who decided this" is what makes a prior decision
weighable rather than oracular -- a decision made by the person you're about to
contradict is a different fact from one made by someone who left last year. They carry
the DATE for the same reason: a decision's age is evidence about its force.
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
    "rebuttal_against. No markdown.\n\n"
    "You may be given PRIOR DECISIONS this team already made, each numbered with its "
    "author and date. Cite them inline as [prior N] wherever they bear on the argument. "
    "A prior decision is EVIDENCE, NOT A VERDICT: cite one in argument_against, or in a "
    "rebuttal, whenever it genuinely cuts that way, and say plainly when a prior decision "
    "looks wrong or has been overtaken by events. Weigh its author and date -- an old "
    "decision, or one made without the evidence now available, carries less force. Never "
    "treat a prior decision as settling the question."
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


def prior_citations(
    db: OrmSession, question: Any, *, member_id: str | None = None, token_budget: int = 800,
) -> list[dict[str, Any]]:
    """Prior decisions worth citing in this question's doc, as citation dicts.

    Each: {ref, id, type, author, date, text}. `ref` is the [prior N] handle the LLM
    cites. Author is a display name, resolved here so the prompt and the rendered doc
    agree on who decided what.

    Never raises: a doc without citations is worse; a doc that 500s is useless.
    """
    from pmqs import repository, retrieval
    from pmqs.models import Member
    from pmqs.outcomes.types import context_text

    try:
        lens_tags = getattr(question, "lens_tags_list", None) or []
        outcomes = retrieval.select_prior_outcomes(
            db,
            product_id=getattr(question, "product_id", None),
            lens=(lens_tags[0] if lens_tags else None),
            topic=getattr(question, "title", None),
            token_budget=token_budget,
            member_id=member_id,
        )
        if not outcomes:
            return []
        ids = {o.author_member_id for o in outcomes if o.author_member_id}
        names = {}
        if ids:
            names = {
                m.id: m.display_name
                for m in db.query(Member).filter(Member.id.in_(ids)).all()
            }
        cites = []
        for i, o in enumerate(outcomes):
            text = context_text(o.type, repository.outcome_payload(o))
            if not text.strip():
                continue
            cites.append({
                "ref": i,
                "id": o.id,
                "type": o.type,
                "author": names.get(o.author_member_id) or "Unknown",
                "date": (o.created_at or "")[:10],
                "text": text,
            })
        return cites
    except Exception as exc:
        log.warning("prior-decision citation lookup failed, continuing without: %s", exc)
        return []


def _prior_block(cites: list[dict[str, Any]]) -> str:
    lines = "\n".join(
        f"[prior {c['ref']}] ({c['type']}, decided by {c['author']} on {c['date']}) {c['text'][:400]}"
        for c in cites
    )
    return (
        "PRIOR DECISIONS BY THIS TEAM (evidence, not verdicts -- argue against them "
        f"where warranted):\n{lines}"
    )


def generate(db: OrmSession, question: Any, *, member_id: str | None = None) -> dict[str, Any]:
    """Generate the Voter-Guide Position Document for a Question. Never raises for LLM."""
    ev = getattr(question, "evidence_list", None) or getattr(question, "evidence", []) or []
    if not llm.is_enabled():
        return _fallback(question)

    # Loop 4: prior decisions from this Product's ledger. A DB read, not a research pass.
    cites = prior_citations(db, question, member_id=member_id)

    parts = [
        f"Decision/question: {getattr(question, 'title', '')}",
        f"Detail: {getattr(question, 'description', '') or ''}",
        f"Evidence: {ev}",
    ]
    if cites:
        parts.append(_prior_block(cites))
    user = "\n".join(parts)
    try:
        result = llm.complete_json(_SYSTEM, user, settings_cfg=settings.get_llm(db), max_tokens=1200)
        if not isinstance(result, dict):
            return _fallback(question)
        # Ensure all sections exist (fill missing with empty string).
        doc: dict[str, Any] = {k: str(result.get(k, "")) for k in SECTIONS}
        doc["evidence"] = ev
        # Persisted with the doc so the rendered citations always match the text that was
        # generated against them -- the ledger moves on, the doc is generate-once.
        doc["prior_decisions"] = cites
        doc["degraded"] = False
        return doc
    except Exception as exc:
        log.warning("position doc generation failed: %s", exc)
        return _fallback(question)
