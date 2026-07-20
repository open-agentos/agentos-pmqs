"""api/outcomes.py — FastAPI routes: Outcomes ledger + push action.

The ledger routes (GET /outcomes, GET /api/outcomes) support both the legacy
unprefixed mount and /w/{workspace_slug}/... (see #56), same pattern as
api/inbox.py. Routes keyed by session_id or outcome_id don't need a slug in the
path -- the Session already carries its own product_id from creation (#52), so
outcomes created against it inherit that scoping automatically.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import members, products, repository
from pmqs.db import get_session
from pmqs.outcomes import push_question_to_issue
from pmqs.outcomes.receipt import display_title, location_for, outcome_markdown
from pmqs.outcomes.types import (
    OutcomeValidationError,
    build_document,
    build_meeting,
    build_policy,
    build_question,
)
from pmqs.web.render import render_error, render_outcomes

router = APIRouter()


@router.get("/outcomes", response_class=HTMLResponse)
@router.get("/w/{workspace_slug}/outcomes", response_class=HTMLResponse)
def outcomes_page(workspace_slug: str | None = None, db: OrmSession = Depends(get_session)):
    try:
        product_id = products.resolve_product_id(db, workspace_slug)
    except KeyError:
        return HTMLResponse(render_error(f"No such product workspace: {workspace_slug}", 404), status_code=404)
    return HTMLResponse(render_outcomes(db, product_id=product_id, workspace_slug=workspace_slug))


@router.get("/api/outcomes")
@router.get("/w/{workspace_slug}/api/outcomes")
def list_outcomes(workspace_slug: str | None = None, db: OrmSession = Depends(get_session)):
    try:
        product_id = products.resolve_product_id(db, workspace_slug)
    except KeyError:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Product-scoped and visibility-filtered per build-spec §4/§5 -- all members'
    # outcomes, minus other members' private rooms.
    viewer_id = members.current_member_id(db)
    return JSONResponse(
        [
            {
                "id": o.id,
                "type": o.type,
                "github_ref": o.github_ref,
                "created_at": o.created_at,
                "author_member_id": o.author_member_id,
                "promoted_at": o.promoted_at,
                "retired_at": o.retired_at,
            }
            for o in repository.list_ledger_outcomes(db, product_id=product_id, member_id=viewer_id)
        ]
    )


@router.post("/questions/{qid}/push-issue")
def push_issue(qid: str, db: OrmSession = Depends(get_session)):
    q = repository.get_question(db, qid)
    if q is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    result = push_question_to_issue(db, q)
    loc = location_for("issue", github_ref=result.get("github_ref"))
    return JSONResponse({"title": q.title, "location": loc, **result})


# --- Phase 2/3: typed outcomes from the war-room outcome bar ---
# Issue is the only type promoted to real GitHub. policy|document|meeting|question are
# hosted-store rows only. A policy MUST NEVER carry a github_ref (enforced in
# repository.create_outcome and reasserted in outcomes/types.py).


@router.post("/workspace/{session_id}/draft")
def draft_outcome(
    session_id: str,
    type: str = Form(...),
    db: OrmSession = Depends(get_session),
):
    """Wave 2: draft an outcome of `type` from the session context, editable in the war
    room's Draft tab. Does NOT persist — a draft becomes an outcome only on confirm
    (POST .../outcome). Never 500s on the LLM; a degraded stub is still a usable draft.
    """
    from pmqs.outcomes.draft import DRAFT_FIELDS, generate_draft

    session = repository.get_session_row(db, session_id)
    if session is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if type not in DRAFT_FIELDS:
        return JSONResponse({"error": f"unknown outcome type: {type}"}, status_code=400)
    return JSONResponse(generate_draft(db, session, type))


@router.post("/workspace/{session_id}/suggest-outcome")
def suggest_outcome_endpoint(session_id: str, db: OrmSession = Depends(get_session)):
    """Wave 4: on wrap-up, recommend the single best outcome (type + draft title +
    rationale). Suggestion only — never creates. Cheap (one short LLM call), fail-open.
    """
    from pmqs.outcomes.suggest import suggest_outcome

    session = repository.get_session_row(db, session_id)
    if session is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(suggest_outcome(db, session))


# Fixed, PM-facing close reasons — the three that distinguish "nothing warranted" from
# "the tool failed me" (build-spec §4.5). Free-form isn't offered; these are the signal.
CLOSE_REASONS = {"no_decision_yet", "decided_nothing_to_record", "couldnt_get_what_i_needed"}


@router.post("/workspace/{session_id}/close")
def close_session_endpoint(
    session_id: str,
    reason: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    """Wave 4: close a room, optionally recording WHY when it produced no outcome, so a
    null outcome becomes a signal. Optional and never a gate — reason may be empty.
    """
    reason = (reason or "").strip()
    if reason and reason not in CLOSE_REASONS:
        return JSONResponse({"error": f"unknown close reason: {reason}"}, status_code=400)
    s = repository.close_session(db, session_id, reason=reason or None)
    if s is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": s.id, "status": s.status, "close_reason": s.close_reason})


@router.post("/workspace/{session_id}/outcome")
def create_typed_outcome(
    session_id: str,
    type: str = Form(...),
    title: str = Form(default=""),
    body: str = Form(default=""),
    agenda: str = Form(default=""),
    calendar_link: str = Form(default=""),
    question_id: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    session = repository.get_session_row(db, session_id)
    product_id = session.product_id if session is not None else None

    # The question this outcome resolves. Prefer an explicit form field, but fall back to
    # the session's own question_id (room <-> question is 1:1) so committing an outcome
    # closes the loop without the draft->commit JS having to carry the id. This is the
    # fix for the dead end where an outcome committed and its Inbox question sat untouched.
    resolved_qid = (question_id or (session.question_id if session is not None else "")) or ""

    if type == "issue":
        # Promote to real GitHub. Prefer the resolved Question; only fabricate one if the
        # room truly had none (a self-directed session), rather than orphaning the real
        # Inbox item behind a fresh ad-hoc duplicate.
        q = repository.get_question(db, resolved_qid) if resolved_qid else None
        if q is None:
            # Create an ad-hoc Question from the session summary so the push path is uniform.
            q = repository.create_question(
                db, title=title or "War-room issue", source="pm", description=body,
                product_id=product_id,
            )
        from pmqs.outcomes.tracker import TrackerNotConfigured
        try:
            result = push_question_to_issue(db, q, session_id=session_id)
        except TrackerNotConfigured as exc:
            # e.g. Jira selected but not wired — surface it as a clean receipt error.
            return JSONResponse({"error": str(exc)}, status_code=400)
        # Receipt: tell the war room exactly what was made and where it now lives.
        loc = location_for("issue", github_ref=result.get("github_ref"))
        repository.add_event(
            db, session_id, kind="outcome",
            label=f"▤ Issue filed — {q.title}", ref=result.get("github_ref"),
        )
        return JSONResponse(
            {"type": "issue", "title": q.title, "location": loc, **result}
        )

    # Non-Issue types: build a validated per-type payload; hosted-store only.
    try:
        if type == "policy":
            payload = build_policy(body or title)  # policy is free-form text
        elif type == "document":
            payload = build_document(title, body)
        elif type == "meeting":
            payload = build_meeting(title, agenda, calendar_link)
        elif type == "question":
            payload = build_question(title, body)
        else:
            return JSONResponse({"error": f"unknown outcome type: {type}"}, status_code=400)
    except OutcomeValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    outcome = repository.create_outcome(
        db,
        type=type,
        payload=payload,
        session_id=session_id,
        github_ref=None,  # hosted-store only; policy can never be pushed
        product_id=product_id,
    )
    # Receipt: hosted-store outcomes land in the ledger — that is their "where".
    # export_url makes Document/Meeting portable (copy / download .md / open-in-tab).
    _GLYPH = {"policy": "§", "document": "✎", "meeting": "◷", "question": "?"}
    _VERB = {"policy": "saved", "document": "drafted", "meeting": "scheduled", "question": "raised"}
    title_str = display_title(type, payload)
    repository.add_event(
        db, session_id, kind="outcome",
        label=f"{_GLYPH.get(type, '•')} {type.title()} {_VERB.get(type, 'created')} — {title_str}",
    )
    # Close the loop: the question that triggered this room is now resolved, so it leaves
    # the Inbox and shows in the ledger as decided. Without this the outcome bar was a
    # dead end -- work happened, the Inbox never changed, and no momentum was felt.
    resolved_title = None
    if resolved_qid:
        rq = repository.mark_question_answered(db, resolved_qid)
        if rq is not None:
            resolved_title = rq.title
            repository.add_event(
                db, session_id, kind="outcome",
                label=f"✓ Resolved — {resolved_title}",
            )
    return JSONResponse({
        "type": type,
        "outcome_id": outcome.id,
        "github_ref": None,
        "title": display_title(type, payload),
        "location": location_for(type),
        "export_url": f"/outcomes/{outcome.id}/export.md",
        "resolved_question": resolved_title,
    })


@router.post("/outcomes/{outcome_id}/deactivate")
def deactivate_outcome(outcome_id: str, db: OrmSession = Depends(get_session)):
    o = repository.deactivate_outcome(db, outcome_id)
    if o is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # `active` is now derived from retired_at (build-spec §7) rather than stored; the
    # response keeps it for existing callers and adds the timestamp behind it.
    return JSONResponse({"id": o.id, "active": o.active, "retired_at": o.retired_at})


@router.post("/outcomes/{outcome_id}/promote")
def promote_outcome(outcome_id: str, db: OrmSession = Depends(get_session)):
    """Promote a private room's outcome to the Product ledger (build-spec §4 rule 3).

    409 rather than a silent no-op when the Product can already see it: promotion is
    one-way (§4 rule 4) and there is no demote, so "already shared" is a state the caller
    was wrong about, not one to shrug at.
    """
    try:
        o = repository.promote_outcome(db, outcome_id)
    except repository.OutcomeAlreadySharedError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if o is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": o.id, "promoted_at": o.promoted_at})


@router.get("/outcomes/{outcome_id}/export.md")
def export_outcome_markdown(
    outcome_id: str, download: int = 0, db: OrmSession = Depends(get_session)
):
    """Export an outcome as Markdown (Wave 3). `?download=1` sets an attachment
    filename; without it the page opens inline (open-in-tab). The client's copy button
    fetches the same text. This is what makes a Document portable — the whole value of
    producing it in PMQs is that it drops cleanly into any tool the PM already uses.
    """
    o = repository.get_outcome(db, outcome_id)
    if o is None:
        return PlainTextResponse("not found", status_code=404)
    md = outcome_markdown(o.type, repository.outcome_payload(o))
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{o.type}-{outcome_id[:8]}.md"'
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8", headers=headers)
