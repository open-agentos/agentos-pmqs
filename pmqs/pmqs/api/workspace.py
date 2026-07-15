"""api/workspace.py — war-room Workspace routes (Phase 2).

Cost discipline: the 8-lens pass runs ONLY via POST /run-lenses (explicit button).
Position Documents generate ONCE (no-op if already present).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import lenses, position_doc, repository, warroom
from pmqs.agentos_client import AgentOSClient
from pmqs.db import get_session
from pmqs.web.render import render_workspace

router = APIRouter()


def _evidence_for(db: OrmSession, session) -> list[dict]:
    if session.question_id:
        q = repository.get_question(db, session.question_id)
        if q is not None:
            return q.evidence_list
    return []


def _proposed_for(db: OrmSession, session) -> list:
    # Proposed questions produced for this session are source='system', status='proposed'.
    # For the prototype, show all currently-proposed system questions.
    return [q for q in repository.list_questions(db) if q.status == "proposed" and q.source == "system"]


@router.post("/workspace/open")
def open_workspace(question_id: str = Form(default=""), db: OrmSession = Depends(get_session)):
    qid = question_id or None
    topic = None
    # Resolve a Phase-0 live-read pseudo-id 'issue:<number>' by persisting the raw
    # issue as a Question on demand (cheap, no LLM) so the war-room has a real anchor.
    if qid and qid.startswith("issue:"):
        number = qid.split(":", 1)[1]
        try:
            state = AgentOSClient().get_state()
            issue = next((i for i in state.get("issues", []) if str(i.get("number")) == number), None)
        except Exception:
            issue = None
        if issue is not None:
            ref = f"#{issue.get('number')}"
            q = repository.create_question(
                db,
                title=issue.get("title", ""),
                source="system",
                description=issue.get("body") or "",
                evidence=[{"type": "issue", "ref": ref, "url": issue.get("url", "")}],
                status="proposed",
            )
            qid = q.id
            topic = q.title
        else:
            qid = None
    elif qid:
        q = repository.get_question(db, qid)
        topic = q.title if q else None
    sess = repository.open_session(db, topic=topic, question_id=qid)
    return RedirectResponse(url=f"/workspace/{sess.id}", status_code=303)


@router.get("/workspace/{session_id}", response_class=HTMLResponse)
def workspace_view(session_id: str, db: OrmSession = Depends(get_session)):
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return HTMLResponse("<h1>Session not found</h1>", status_code=404)
    doc = json.loads(sess.position_doc) if sess.position_doc else None
    return HTMLResponse(
        render_workspace(
            sess,
            repository.list_messages(db, session_id),
            _evidence_for(db, sess),
            _proposed_for(db, sess),
            doc,
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
