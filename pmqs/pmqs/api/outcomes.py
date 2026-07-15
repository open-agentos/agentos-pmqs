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
