"""api/inbox.py — FastAPI routes: list/score/filter/quick-add + Phase 0 render.

GET  /                 -> full mockup HTML with real Inbox cards (ranked)
POST /refresh          -> run trigger pipeline against live AgentOS state, persist
POST /quick-add        -> create a source='pm' Question (scored by same formula)
POST /questions/{id}/status -> update status (saved/dismissed/...)
GET  /api/questions    -> JSON list (debug/inspection)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import repository, scoring
from pmqs.agentos_client import AgentOSClient
from pmqs.db import get_session
from pmqs.pipeline import generate
from pmqs.web.render import render_inbox

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(lens: str | None = Query(default=None), db: OrmSession = Depends(get_session)):
    questions = repository.list_questions(db, lens_tag=lens)
    # Phase 0 fallback: if the store is empty (no pipeline run yet), render live
    # AgentOS issues directly so `/` shows a real Inbox out of the box.
    if not questions:
        try:
            state = AgentOSClient().get_state()
            questions = _live_shims(state)
        except Exception:
            questions = []
    return HTMLResponse(render_inbox(questions))


def _live_shims(state):
    """Phase 0 read-through: map raw Issues into flat Question-shaped shims."""
    shims = []
    for issue in state.get("issues", []):
        ref = f"#{issue.get('number')}"
        shims.append(
            _Shim(
                title=issue.get("title", ""),
                description=issue.get("body") or "",
                lens_tags=[],
                evidence=[{"type": "issue", "ref": ref, "url": issue.get("url", "")}],
                source="system",
                status="proposed",
                score=None,
            )
        )
    return shims


class _Shim:
    """Minimal duck-typed stand-in for a Question (Phase 0 live render only)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def lens_tags_list(self):
        return self.__dict__.get("lens_tags", [])

    @property
    def evidence_list(self):
        return self.__dict__.get("evidence", [])


@router.post("/refresh")
def refresh(db: OrmSession = Depends(get_session)):
    state = AgentOSClient().get_state()
    questions = generate(db, state)
    return JSONResponse({"generated": len(questions), "ids": [q.id for q in questions]})


@router.post("/quick-add")
def quick_add(title: str = Form(...), lens: str = Form(default=""), db: OrmSession = Depends(get_session)):
    lens_tags = [lens] if lens else []
    q = repository.create_question(db, title=title, source="pm", lens_tags=lens_tags, status="proposed")
    score, dims = scoring.score_question(q)
    repository.set_question_score(db, q.id, score, dims)
    return RedirectResponse(url="/", status_code=303)


@router.post("/questions/{qid}/status")
def set_status(qid: str, status: str = Form(...), db: OrmSession = Depends(get_session)):
    q = repository.update_question_status(db, qid, status)
    if q is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": q.id, "status": q.status})


@router.get("/api/questions")
def api_questions(lens: str | None = Query(default=None), db: OrmSession = Depends(get_session)):
    qs = repository.list_questions(db, lens_tag=lens)
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
