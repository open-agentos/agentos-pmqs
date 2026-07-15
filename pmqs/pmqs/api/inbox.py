"""api/inbox.py — FastAPI routes: list/score/filter/quick-add + Inbox render.

GET  /                         -> Inbox HTML (persisted questions, ranked; always Inbox view)
POST /refresh                  -> run trigger pipeline against live AgentOS state, persist
POST /quick-add                -> create a source='pm' Question
POST /questions/{id}/status    -> update status (saved/dismissed/...) then redirect to /
GET  /api/questions            -> JSON list (debug/inspection; include_all)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import repository, scoring
from pmqs.agentos_client import AgentOSClient
from pmqs.db import get_session
from pmqs.pipeline import generate
from pmqs.resolve import resolve_question_id
from pmqs.web.render import render_inbox

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(
    lens: str | None = Query(default=None),
    source: str | None = Query(default=None),
    news: str | None = Query(default=None),
    db: OrmSession = Depends(get_session),
):
    # Canonical Inbox = persisted questions (proposed + saved), ranked. No silent swap to
    # a live-GitHub view — an empty store shows an explicit empty-state (see render_inbox).
    questions = repository.list_questions(db, lens_tag=lens, source=source)
    return HTMLResponse(render_inbox(questions, flash=news))


@router.post("/refresh")
def refresh(db: OrmSession = Depends(get_session)):
    # Pull questions from the repo via the structural-trigger pipeline, then show the Inbox.
    state = AgentOSClient().get_state()
    generate(db, state)
    return RedirectResponse(url="/", status_code=303)


@router.post("/quick-add")
def quick_add(title: str = Form(...), lens: str = Form(default=""), db: OrmSession = Depends(get_session)):
    lens_tags = [lens] if lens else []
    q = repository.create_question(db, title=title, source="pm", lens_tags=lens_tags, status="proposed")
    score, dims = scoring.score_question(q)
    repository.set_question_score(db, q.id, score, dims)
    return RedirectResponse(url="/", status_code=303)


@router.post("/questions/{qid}/status")
def set_status(qid: str, status: str = Form(...), db: OrmSession = Depends(get_session)):
    # Resolve pseudo-ids (issue:<n>) to a real persisted Question first (B3), so the
    # Save/Dismiss buttons work even on a fresh live-read Inbox.
    real_id = resolve_question_id(db, qid)
    if real_id is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    repository.update_question_status(db, real_id, status)
    # Browser button path → redirect back to the Inbox (not a JSON blob).
    return RedirectResponse(url="/", status_code=303)


@router.get("/api/questions")
def api_questions(
    lens: str | None = Query(default=None),
    include_all: bool = Query(default=False),
    db: OrmSession = Depends(get_session),
):
    qs = repository.list_questions(db, lens_tag=lens, include_all=include_all)
    return JSONResponse(
        [
            {
                "id": q.id,
                "title": q.title,
                "status": q.status,
                "source": q.source,
                "lens_tags": q.lens_tags_list,
                "score": q.score,
                "score_dims": q.score_dims_dict,
                "evidence": q.evidence_list,
            }
            for q in qs
        ]
    )
