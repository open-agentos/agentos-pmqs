"""draft.py — generate an outcome draft from the war-room session context (Wave 2).

Removes the "didn't know HOW" confound. Choosing an outcome type doesn't ask the PM
to write it from a blank box — it drafts the artifact from everything the session
already holds (conversation, position doc, evidence, and the Product's standing
policies via the context-feed), then hands it back editable. The PM reviews and
commits; the system drafts, the PM decides.

Mirrors position_doc.py deliberately: ONE LLM round-trip, strict JSON schema, and a
graceful fallback that never blocks — if the model is unreachable the PM still gets an
editable stub and can write and commit the outcome by hand. Losing the outcome to a
silent failure is the one unrecoverable error here, so we fail open.

Nothing here persists anything. A draft becomes real only when the PM confirms it and
the existing typed-outcome endpoint writes the ledger row.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import context_feed, llm, repository, settings

log = logging.getLogger(__name__)

# The editable fields each type's draft returns. The keys match what the typed-outcome
# endpoint (api/outcomes.create_typed_outcome) accepts, so a confirmed draft commits
# with no translation layer.
DRAFT_FIELDS: dict[str, tuple[str, ...]] = {
    "issue": ("title", "body"),
    "document": ("title", "body"),
    "meeting": ("title", "agenda"),
    "policy": ("text",),
    "question": ("title", "body"),
}

_TYPE_GUIDANCE = {
    "issue": (
        "Draft a GitHub Issue for engineering. 'title' is a crisp imperative summary. "
        "'body' states the problem, why it matters, acceptance criteria, and cites the "
        "relevant evidence (issue/PR/run refs) from the context."
    ),
    "document": (
        "Draft the briefing/analysis this session produced (a PRD, competitive brief, "
        "or decision memo as fits). 'title' names it; 'body' is the full prose document "
        "grounded strictly in the session's evidence and conclusions."
    ),
    "meeting": (
        "Draft a meeting to carry this decision forward. 'title' names it; 'agenda' is a "
        "tight ordered agenda of the points that actually need a room, drawn from the "
        "session's open threads."
    ),
    "policy": (
        "Draft a standing rule (like agent 'Memory') capturing the durable decision this "
        "session reached. 'text' is the rule in plain language — what holds, and when it "
        "applies. One or two sentences; no preamble."
    ),
    "question": (
        "Draft a sharper follow-up question for the inbox. 'title' is the question; "
        "'body' is a one-line note on why it's worth asking now."
    ),
}

_MAX_TOKENS = int(os.environ.get("PMQS_DRAFT_MAX_TOKENS", "1200"))


def _session_context(db: OrmSession, session: Any) -> str:
    """Everything the draft should be grounded in, as one text blob."""
    parts: list[str] = []
    if getattr(session, "topic", None):
        parts.append(f"Session topic: {session.topic}")

    qid = getattr(session, "question_id", None)
    if qid:
        q = repository.get_question(db, qid)
        if q is not None:
            parts.append(f"Originating question: {q.title}")
            if q.description:
                parts.append(f"Question detail: {q.description[:500]}")
            ev = q.evidence_list
            if ev:
                refs = ", ".join(
                    f"{e.get('type', '')} {e.get('ref', '')} {e.get('url', '')}".strip()
                    for e in ev
                )
                parts.append(f"Evidence: {refs}")

    # The position doc is the richest artifact the session may already hold. It's a raw
    # JSON TEXT column (generate-once, Phase 2) — parse defensively, never let a bad
    # blob sink the draft.
    doc = None
    raw = getattr(session, "position_doc", None)
    if raw:
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError):
            doc = None
    if isinstance(doc, dict) and doc.get("summary"):
        parts.append(f"Position-doc summary: {doc.get('summary', '')[:600]}")
        if doc.get("what_your_vote_means"):
            parts.append(f"What the decision means: {doc['what_your_vote_means'][:400]}")

    msgs = repository.list_messages(db, session.id)
    if msgs:
        convo = "\n".join(
            f"{m.role.upper()}: {m.content}" for m in msgs[-24:]  # last 24 turns is plenty
        )
        parts.append(f"Conversation:\n{convo}")

    return "\n\n".join(parts)


def _fallback(otype: str, session: Any) -> dict[str, Any]:
    topic = getattr(session, "topic", "") or ""
    note = "[draft not generated — the model was unreachable. Write it yourself and commit.]"
    fields = {k: "" for k in DRAFT_FIELDS[otype]}
    # Seed the title-ish field with the topic so the PM isn't fully cold-starting.
    if "title" in fields:
        fields["title"] = topic
    body_key = "body" if "body" in fields else ("agenda" if "agenda" in fields else "text")
    fields[body_key] = note
    return {"type": otype, "fields": fields, "degraded": True}


def generate_draft(db: OrmSession, session: Any, otype: str) -> dict[str, Any]:
    """Draft an outcome of `otype` from the session context. Never raises for the LLM.

    Returns {type, fields:{...}, degraded:bool}. `fields` keys are exactly
    DRAFT_FIELDS[otype], ready to POST to the typed-outcome endpoint on confirm.
    """
    if otype not in DRAFT_FIELDS:
        raise ValueError(f"unknown outcome type: {otype}")

    if not llm.is_enabled():
        return _fallback(otype, session)

    keys = DRAFT_FIELDS[otype]
    system = (
        "You draft a concrete product-management outcome from a war-room session, "
        "grounded strictly in the provided context. " + _TYPE_GUIDANCE[otype] + " "
        f"Respond as JSON with EXACTLY these keys: {', '.join(keys)}. No markdown, no "
        "commentary outside the JSON."
    )

    context = _session_context(db, session)
    # Standing policies constrain the draft too — a document or issue should already
    # respect the team's durable rules (context_feed = the unified feed, product-scoped).
    context = context_feed.augment(
        context, context_feed.build_context_block(db, product_id=getattr(session, "product_id", None))
    )
    user = f"{context}\n\nDraft the {otype} now as JSON."

    try:
        result = llm.complete_json(
            system, user, settings_cfg=settings.get_llm(db), max_tokens=_MAX_TOKENS
        )
        if not isinstance(result, dict):
            return _fallback(otype, session)
        fields = {k: str(result.get(k, "")).strip() for k in keys}
        # An all-empty draft is worse than the stub — the PM at least gets a prompt.
        if not any(fields.values()):
            return _fallback(otype, session)
        return {"type": otype, "fields": fields, "degraded": False}
    except Exception as exc:
        log.warning("draft generation failed for %s: %s", otype, exc)
        return _fallback(otype, session)
