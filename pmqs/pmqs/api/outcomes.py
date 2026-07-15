"""api/outcomes.py — FastAPI routes: Outcomes ledger + push action."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import repository
from pmqs.db import get_session
from pmqs.outcomes import push_question_to_issue

router = APIRouter()


@router.get("/api/outcomes")
def list_outcomes(db: OrmSession = Depends(get_session)):
    return JSONResponse(
        [
            {
                "id": o.id,
                "type": o.type,
                "github_ref": o.github_ref,
                "created_at": o.created_at,
            }
            for o in repository.list_outcomes(db)
        ]
    )


@router.post("/questions/{qid}/push-issue")
def push_issue(qid: str, db: OrmSession = Depends(get_session)):
    q = repository.get_question(db, qid)
    if q is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    result = push_question_to_issue(db, q)
    return JSONResponse(result)


# --- Phase 2: typed outcomes from the war-room outcome bar ---
# Issue is the only type promoted to real GitHub. policy|document|meeting|question are
# written as hosted-store rows only. A policy MUST NEVER carry a github_ref (enforced in
# repository.create_outcome). No per-type context-feed is built here — that is Phase 3.
_HOSTED_TYPES = {"policy", "document", "meeting", "question"}


@router.post("/workspace/{session_id}/outcome")
def create_typed_outcome(
    session_id: str,
    type: str = Form(...),
    title: str = Form(default=""),
    body: str = Form(default=""),
    question_id: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    if type == "issue":
        # Promote to real GitHub. Prefer a linked Question if provided.
        q = repository.get_question(db, question_id) if question_id else None
        if q is None:
            # Create an ad-hoc Question from the session summary so the push path is uniform.
            q = repository.create_question(
                db, title=title or "War-room issue", source="pm", description=body,
            )
        result = push_question_to_issue(db, q, session_id=session_id)
        return JSONResponse({"type": "issue", **result})

    if type in _HOSTED_TYPES:
        outcome = repository.create_outcome(
            db,
            type=type,
            payload={"title": title, "body": body},
            session_id=session_id,
            github_ref=None,  # hosted-store only; policy can never be pushed
        )
        return JSONResponse({"type": type, "outcome_id": outcome.id, "github_ref": None})

    return JSONResponse({"error": f"unknown outcome type: {type}"}, status_code=400)
