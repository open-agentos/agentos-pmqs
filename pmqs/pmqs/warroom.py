"""warroom.py — decision-oriented war-room conversation engine (Phase 2 task 1).

Probes and challenges the PM's thinking to surface what's true before they decide —
NOT adversarial counter-argument theater (product-design.md). One LLM round-trip per
PM message. LLM failure yields a graceful fallback assistant message; the session and
its history stay intact (Phase 1 degrade-gracefully discipline).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import context_feed, llm, repository, settings

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a war-room thinking partner for a product manager making a specific "
    "decision. Your job is to PROBE and pressure-test their reasoning and surface what "
    "is actually true from the evidence — not to argue for the sake of arguing, and not "
    "to play devil's advocate theater. Be concise and decision-oriented: the PM leads "
    "and decides. Ask sharp questions, point out what the evidence does and doesn't "
    "support, and name real trade-offs. Keep replies to a few sentences.\n"
    "Format replies in Markdown (bold, bullet lists, `code`). When you refer to a "
    "specific source — an issue, PR, run, document, or news item — cite it and, when a "
    "URL for it is given in the context, link to it with a Markdown link like "
    "[#47](url). Ground claims in the provided evidence rather than asserting them "
    "uncited; if the evidence doesn't cover something, say so."
)

_FALLBACK = (
    "[LLM unavailable] I can't reach the model right now, so I can't probe this further "
    "yet. Your message is saved — check Settings (LLM provider) or try again."
)


def _context_preamble(db: OrmSession, session: Any) -> str:
    parts = []
    if session.topic:
        parts.append(f"Session topic: {session.topic}")
    if session.question_id:
        q = repository.get_question(db, session.question_id)
        if q is not None:
            parts.append(f"Originating question: {q.title}")
            if q.description:
                parts.append(f"Question detail: {q.description[:500]}")
            ev = q.evidence_list
            if ev:
                # Present each source with its URL so the model can produce real links.
                lines = []
                for e in ev:
                    ref = f"{e.get('type','')} {e.get('ref','')}".strip()
                    url = (e.get("url") or "").strip()
                    lines.append(f"- {ref} — {url}" if url else f"- {ref}")
                parts.append("Sources (cite these; link when a URL is given):\n" + "\n".join(lines))
    return "\n".join(parts)


def respond(db: OrmSession, session_id: str, pm_message: str) -> Any:
    """Append the PM message, produce + persist an assistant reply. Never raises for LLM."""
    session = repository.get_session_row(db, session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    repository.add_message(db, session_id, role="pm", content=pm_message)

    history = repository.list_messages(db, session_id, dialogue_only=True)
    convo = "\n".join(f"{m.role.upper()}: {m.content}" for m in history)
    user = f"{_context_preamble(db, session)}\n\nConversation so far:\n{convo}\n\nRespond as the war-room partner."
    # Phase 3: prepend the unified context-feed (standing policies, documents, agendas).
    # Scoped to this room's Product (build-spec §5) -- Loop 1: any member's active
    # Policy constrains every member's agents, and nothing crosses the Product.
    user = context_feed.augment(
        user, context_feed.build_context_block(db, product_id=session.product_id)
    )

    reply = _FALLBACK
    if llm.is_enabled():
        try:
            reply = llm.complete(_SYSTEM, user, settings_cfg=settings.get_llm(db), max_tokens=400)
        except Exception as exc:
            log.warning("war-room LLM call failed, using fallback: %s", exc)
            reply = _FALLBACK

    return repository.add_message(db, session_id, role="assistant", content=reply)
