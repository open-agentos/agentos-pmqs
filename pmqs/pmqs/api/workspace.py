"""api/workspace.py — war-room Workspace routes (Phase 2).

Cost discipline: the 8-lens pass runs ONLY via POST /run-lenses (explicit button).
Position Documents generate ONCE (no-op if already present).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import lenses, position_doc, products, repository, warroom
from pmqs.db import get_session
from pmqs.resolve import resolve_question_id
from pmqs.web.render import render_error, render_workspace

router = APIRouter()


def _repo_for(db: OrmSession, workspace_slug: str | None) -> str | None:
    if workspace_slug is None:
        return None
    product = products.get_product_by_slug(db, workspace_slug)
    return product.full_name if product else None


def _evidence_for(db: OrmSession, session) -> list[dict]:
    if session.question_id:
        q = repository.get_question(db, session.question_id)
        if q is not None:
            return q.evidence_list
    return []


def _proposed_for(db: OrmSession, session) -> list:
    # B6: only the proposed questions THIS session's lens run produced (origin scoped),
    # not every proposed system question globally.
    return repository.list_session_proposed(db, session.id)


@router.post("/workspace/open")
@router.post("/w/{workspace_slug}/workspace/open")
def open_workspace(
    workspace_slug: str | None = None,
    question_id: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    try:
        product_id = products.resolve_product_id(db, workspace_slug)
    except KeyError:
        return HTMLResponse(render_error(f"No such product workspace: {workspace_slug}", 404), status_code=404)
    repo = _repo_for(db, workspace_slug)
    prefix = f"/w/{workspace_slug}" if workspace_slug else ""

    # Resolve pseudo-ids (issue:<n>) to a real Question (shared helper).
    qid = resolve_question_id(db, question_id, repo=repo, product_id=product_id) if question_id else None

    # B0b: reuse the existing open session for this question so its Position Doc and
    # conversation persist across visits — don't spawn a fresh empty session each time.
    if qid:
        existing = repository.find_open_session_for_question(db, qid)
        if existing is not None:
            return RedirectResponse(url=f"{prefix}/workspace/{existing.id}", status_code=303)

    topic = None
    if qid:
        q = repository.get_question(db, qid)
        topic = q.title if q else None
    sess = repository.open_session(db, topic=topic, question_id=qid, product_id=product_id)
    return RedirectResponse(url=f"{prefix}/workspace/{sess.id}", status_code=303)


@router.get("/workspace/{session_id}", response_class=HTMLResponse)
def workspace_view(session_id: str, db: OrmSession = Depends(get_session)):
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return HTMLResponse(render_error("War-room session not found.", 404), status_code=404)
    doc = json.loads(sess.position_doc) if sess.position_doc else None
    product = products.get_product(db, sess.product_id) if sess.product_id else None
    return HTMLResponse(
        render_workspace(
            sess,
            repository.list_messages(db, session_id),
            _evidence_for(db, sess),
            _proposed_for(db, sess),
            doc,
            db=db,
            workspace_slug=product.slug if product else None,
        )
    )


@router.post("/workspace/{session_id}/message")
def workspace_message(session_id: str, content: str = Form(...), db: OrmSession = Depends(get_session)):
    warroom.respond(db, session_id, content)
    return RedirectResponse(url=f"/workspace/{session_id}", status_code=303)


@router.post("/workspace/{session_id}/run-lenses")
def workspace_run_lenses(session_id: str, db: OrmSession = Depends(get_session)):
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    produced = lenses.run_session_lenses(db, sess)
    return RedirectResponse(url=f"/workspace/{session_id}", status_code=303)


@router.post("/workspace/{session_id}/position-doc")
def workspace_position_doc(session_id: str, db: OrmSession = Depends(get_session)):
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Generate ONCE: no-op if already present (per resolved Q2).
    if not sess.position_doc and sess.question_id:
        q = repository.get_question(db, sess.question_id)
        if q is not None:
            doc = position_doc.generate(db, q)
            repository.set_position_doc(db, session_id, doc)
    return RedirectResponse(url=f"/workspace/{session_id}", status_code=303)


@router.post("/workspace/{session_id}/branch")
def workspace_branch(session_id: str, topic: str = Form(...), db: OrmSession = Depends(get_session)):
    child = repository.open_session(db, topic=topic, parent_id=session_id)
    return RedirectResponse(url=f"/workspace/{child.id}", status_code=303)


@router.post("/workspace/{session_id}/proposed/{qid}/add")
def workspace_add_proposed(session_id: str, qid: str, db: OrmSession = Depends(get_session)):
    # "Add to inbox": acknowledge a proposed question by marking it saved so it pins in
    # the ranked Inbox list. It's already scored/visible; this records the PM's intent.
    repository.update_question_status(db, qid, "saved")
    return RedirectResponse(url=f"/workspace/{session_id}", status_code=303)
