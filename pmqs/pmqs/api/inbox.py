"""api/inbox.py — FastAPI routes: list/score/filter/quick-add + Inbox render.

Mounted twice by api/app.py (see #56): once unprefixed (legacy, no workspace
filter -- every route here accepts workspace_slug=None and behaves exactly as
before) and once under /w/{workspace_slug}/... (resolves to that Workspace's own
Questions/repo). Same handlers serve both; `workspace_slug` is a path param in the
scoped mount and simply absent (defaulting to None) in the legacy one.

GET  /[w/{slug}/]                       -> Inbox HTML (persisted questions, ranked)
POST /[w/{slug}/]refresh                -> run trigger pipeline against live AgentOS state
POST /[w/{slug}/]quick-add               -> create a source='pm' Question
POST /[w/{slug}/]questions/{id}/status   -> update status, redirect back to this Inbox
GET  /[w/{slug}/]api/questions           -> JSON list (debug/inspection; include_all)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import products, repository, scoring
from pmqs.agentos_client import AgentOSClient
from pmqs.db import get_session
from pmqs.pipeline import generate
from pmqs.resolve import resolve_question_id
from pmqs.web.render import render_error, render_inbox

router = APIRouter()


def _base(workspace_slug: str | None) -> str:
    """Path prefix to redirect back into, preserving whichever mount served the request."""
    return f"/w/{workspace_slug}" if workspace_slug else ""


def _repo_for(db: OrmSession, workspace_slug: str | None) -> str | None:
    """The repo a scoped workspace's AgentOSClient calls should target. None (i.e. fall
    back to config.AGENTOS_REPO) for the legacy unprefixed mount."""
    if workspace_slug is None:
        return None
    ws = products.get_workspace_by_slug(db, workspace_slug)
    if ws is None:
        return None
    product = products.get_product(db, ws.product_id)
    return product.full_name if product else None


@router.get("/", response_class=HTMLResponse)
@router.get("/w/{workspace_slug}/", response_class=HTMLResponse)
def index(
    workspace_slug: str | None = None,
    lens: str | None = Query(default=None),
    source: str | None = Query(default=None),
    news: str | None = Query(default=None),
    refreshed: str | None = Query(default=None),
    db: OrmSession = Depends(get_session),
):
    try:
        workspace_id = products.resolve_workspace_id(db, workspace_slug)
    except KeyError:
        return HTMLResponse(render_error(f"No such product workspace: {workspace_slug}", 404), status_code=404)
    # Canonical Inbox = persisted questions (proposed + saved), ranked. No silent swap to
    # a live-GitHub view — an empty store shows an explicit empty-state (see render_inbox).
    questions = repository.list_questions(db, lens_tag=lens, source=source, workspace_id=workspace_id)
    return HTMLResponse(render_inbox(questions, flash=news, refreshed=refreshed))


@router.post("/refresh")
@router.post("/w/{workspace_slug}/refresh")
def refresh(workspace_slug: str | None = None, db: OrmSession = Depends(get_session)):
    try:
        workspace_id = products.resolve_workspace_id(db, workspace_slug)
    except KeyError:
        return HTMLResponse(render_error(f"No such product workspace: {workspace_slug}", 404), status_code=404)
    repo = _repo_for(db, workspace_slug)
    # Pull questions from the repo via the structural-trigger pipeline, then show the Inbox
    # with a banner reporting how many were generated (0 is a valid, explained result).
    state = AgentOSClient(repo=repo).get_state() if repo else AgentOSClient().get_state()
    generated = generate(db, state, workspace_id=workspace_id)
    return RedirectResponse(url=f"{_base(workspace_slug)}/?refreshed={len(generated)}", status_code=303)


@router.post("/quick-add")
@router.post("/w/{workspace_slug}/quick-add")
def quick_add(
    workspace_slug: str | None = None,
    title: str = Form(...),
    lens: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    try:
        workspace_id = products.resolve_workspace_id(db, workspace_slug)
    except KeyError:
        return HTMLResponse(render_error(f"No such product workspace: {workspace_slug}", 404), status_code=404)
    lens_tags = [lens] if lens else []
    q = repository.create_question(
        db, title=title, source="pm", lens_tags=lens_tags, status="proposed", workspace_id=workspace_id
    )
    score, dims = scoring.score_question(q)
    repository.set_question_score(db, q.id, score, dims)
    return RedirectResponse(url=f"{_base(workspace_slug)}/", status_code=303)


@router.post("/questions/{qid}/status")
@router.post("/w/{workspace_slug}/questions/{qid}/status")
def set_status(qid: str, workspace_slug: str | None = None, status: str = Form(...), db: OrmSession = Depends(get_session)):
    # Resolve pseudo-ids (issue:<n>) to a real persisted Question first (B3), so the
    # Save/Dismiss buttons work even on a fresh live-read Inbox.
    try:
        workspace_id = products.resolve_workspace_id(db, workspace_slug)
    except KeyError:
        return JSONResponse({"error": "not found"}, status_code=404)
    repo = _repo_for(db, workspace_slug)
    real_id = resolve_question_id(db, qid, repo=repo, workspace_id=workspace_id)
    if real_id is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    repository.update_question_status(db, real_id, status)
    # Browser button path → redirect back to the Inbox (not a JSON blob).
    return RedirectResponse(url=f"{_base(workspace_slug)}/", status_code=303)


@router.get("/api/questions")
@router.get("/w/{workspace_slug}/api/questions")
def api_questions(
    workspace_slug: str | None = None,
    lens: str | None = Query(default=None),
    include_all: bool = Query(default=False),
    db: OrmSession = Depends(get_session),
):
    try:
        workspace_id = products.resolve_workspace_id(db, workspace_slug)
    except KeyError:
        return JSONResponse({"error": "not found"}, status_code=404)
    qs = repository.list_questions(db, lens_tag=lens, include_all=include_all, workspace_id=workspace_id)
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
