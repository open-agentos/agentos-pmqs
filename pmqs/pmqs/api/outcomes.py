"""api/outcomes.py — FastAPI routes: Outcomes ledger + push action.

The ledger routes (GET /outcomes, GET /api/outcomes) support both the legacy
unprefixed mount and /w/{workspace_slug}/... (see #56), same pattern as
api/inbox.py. Routes keyed by session_id or outcome_id don't need a slug in the
path -- the Session already carries its own product_id from creation (#52), so
outcomes created against it inherit that scoping automatically.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import products, repository
from pmqs.db import get_session
from pmqs.outcomes import push_question_to_issue
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
    return JSONResponse(
        [
            {
                "id": o.id,
                "type": o.type,
                "github_ref": o.github_ref,
                "created_at": o.created_at,
            }
            for o in repository.list_outcomes(db, product_id=product_id)
        ]
    )


@router.post("/questions/{qid}/push-issue")
def push_issue(qid: str, db: OrmSession = Depends(get_session)):
    q = repository.get_question(db, qid)
    if q is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    result = push_question_to_issue(db, q)
    return JSONResponse(result)


# --- Phase 2/3: typed outcomes from the war-room outcome bar ---
# Issue is the only type promoted to real GitHub. policy|document|meeting|question are
# hosted-store rows only. A policy MUST NEVER carry a github_ref (enforced in
# repository.create_outcome and reasserted in outcomes/types.py).


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

    if type == "issue":
        # Promote to real GitHub. Prefer a linked Question if provided.
        q = repository.get_question(db, question_id) if question_id else None
        if q is None:
            # Create an ad-hoc Question from the session summary so the push path is uniform.
            q = repository.create_question(
                db, title=title or "War-room issue", source="pm", description=body,
                product_id=product_id,
            )
        result = push_question_to_issue(db, q, session_id=session_id)
        return JSONResponse({"type": "issue", **result})

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
    return JSONResponse({"type": type, "outcome_id": outcome.id, "github_ref": None})


@router.post("/outcomes/{outcome_id}/deactivate")
def deactivate_outcome(outcome_id: str, db: OrmSession = Depends(get_session)):
    o = repository.deactivate_outcome(db, outcome_id)
    if o is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # `active` is now derived from retired_at (build-spec §7) rather than stored; the
    # response keeps it for existing callers and adds the timestamp behind it.
    return JSONResponse({"id": o.id, "active": o.active, "retired_at": o.retired_at})
