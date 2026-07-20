"""api/workspace.py — war-room Workspace routes (Phase 2).

Cost discipline: the 8-lens pass runs ONLY via POST /run-lenses (explicit button).
Position Documents generate ONCE (no-op if already present).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import lenses, members, position_doc, products, repository, warroom
from pmqs.db import get_session
from pmqs.resolve import resolve_question_id
from pmqs.web.render import render_error, render_workspace, render_workspace_list

router = APIRouter()


def _wants_json(request: Request) -> bool:
    """The async client (Wave 2) sends X-PMQS-Ajax:1 so actions can live-append to the
    conversation instead of doing a full-page 303 reload. Any other caller (a plain form
    POST, a test hitting the legacy path) still gets the redirect."""
    return request.headers.get("x-pmqs-ajax") == "1"


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
    topic: str = Form(default=""),
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

    # A room's topic: a question's title when opened from the Inbox, otherwise the
    # free-text prompt the PM typed into the nav's "Start a war room" (rec 5 — a
    # self-directed strategic session, not only a reaction to a system-raised question).
    room_topic = topic.strip() or None
    if qid:
        q = repository.get_question(db, qid)
        room_topic = q.title if q else None
    sess = repository.open_session(db, topic=room_topic, question_id=qid, product_id=product_id)
    return RedirectResponse(url=f"{prefix}/workspace/{sess.id}", status_code=303)


@router.get("/workspace/{session_id}", response_class=HTMLResponse)
@router.get("/w/{workspace_slug}/workspace/{session_id}", response_class=HTMLResponse)
def workspace_view(session_id: str, workspace_slug: str | None = None,
                   db: OrmSession = Depends(get_session)):
    """The war room.

    Both mounts render the same room: the rail's product context is derived from the
    SESSION's own product_id either way, never from the URL. `workspace_slug` exists so
    the navigable URL can carry the product prefix like every other navigable route --
    open_workspace() redirects here with it, and the Workspaces list links here with it.
    Until #104 the prefixed twin didn't exist, so both 404'd and the war room was
    unreachable from anywhere under /w/{slug}/.

    A slug that doesn't match the session's product is a 404, not a render. Serving
    product A's room under a URL claiming product B is a crossed data stream, which is
    the one hard requirement on the multi-product work -- and it would put the wrong
    product in the rail and the switcher.
    """
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return HTMLResponse(render_error("War-room session not found.", 404), status_code=404)
    doc = json.loads(sess.position_doc) if sess.position_doc else None
    product = products.get_product(db, sess.product_id) if sess.product_id else None
    if workspace_slug is not None and (product is None or product.slug != workspace_slug):
        return HTMLResponse(
            render_error("War-room session not found in this product.", 404), status_code=404
        )
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
def workspace_message(session_id: str, request: Request, content: str = Form(...), db: OrmSession = Depends(get_session)):
    assistant = warroom.respond(db, session_id, content)
    if _wants_json(request):
        from pmqs.web.render import render_message_html
        return JSONResponse({"assistant_html": render_message_html(assistant)})
    return RedirectResponse(url=f"/workspace/{session_id}", status_code=303)


@router.post("/workspace/{session_id}/run-lenses")
def workspace_run_lenses(session_id: str, request: Request, db: OrmSession = Depends(get_session)):
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    produced = lenses.run_session_lenses(db, sess)
    label = (
        f"⟳ Ran 8-lens pass — {len(produced)} proposed question"
        + ("" if len(produced) == 1 else "s")
    )
    repository.add_event(db, session_id, kind="lenses", label=label, tab="proposed")
    if _wants_json(request):
        from pmqs.web.render import render_event_line, render_proposed_tab_html
        proposed = repository.list_session_proposed(db, sess.id)
        return JSONResponse({
            "event_html": render_event_line(label, "proposed"),
            "tab": "proposed",
            "tab_html": render_proposed_tab_html(proposed, sess.id),
            "tab_count": len(proposed),
        })
    return RedirectResponse(url=f"/workspace/{session_id}", status_code=303)


@router.post("/workspace/{session_id}/position-doc")
def workspace_position_doc(session_id: str, request: Request, db: OrmSession = Depends(get_session)):
    sess = repository.get_session_row(db, session_id)
    if sess is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Generate ONCE: no-op if already present (per resolved Q2).
    generated = False
    no_subject = False
    if not sess.position_doc:
        # Prefer the linked inbox question; if the room isn't linked to one (a free-text
        # war room, or a pseudo-id that never resolved), fall back to the room's own topic
        # so the button still works instead of silently no-opping. Only when there's
        # genuinely nothing to generate from do we skip -- and then we SAY so (below)
        # rather than flashing a busy line and re-rendering the same empty state.
        q = repository.get_question(db, sess.question_id) if sess.question_id else None
        subject = q
        if subject is None and (sess.topic or "").strip():
            from types import SimpleNamespace
            subject = SimpleNamespace(
                title=sess.topic, description="", evidence_list=[], evidence=[],
                product_id=sess.product_id, lens_tags_list=[],
            )
        if subject is not None:
            # member_id so cited prior decisions respect §4 -- a doc must never
            # cite a room the reader isn't allowed to see.
            doc = position_doc.generate(db, subject, member_id=members.current_member_id(db))
            repository.set_position_doc(db, session_id, doc)
            repository.add_event(
                db, session_id, kind="position_doc",
                label="✎ Position document generated", tab="doc",
            )
            generated = True
        else:
            no_subject = True
    if _wants_json(request):
        import json as _json
        from pmqs.web.render import render_event_line, render_position_doc_tab_html
        sess = repository.get_session_row(db, session_id)
        doc = _json.loads(sess.position_doc) if sess and sess.position_doc else None
        if no_subject:
            event = render_event_line(
                "✕ Nothing to generate from — this room has no question or topic.", None)
        elif generated:
            event = render_event_line("✎ Position document generated", "doc")
        else:
            event = ""
        return JSONResponse({
            "event_html": event,
            "tab": "doc",
            "tab_html": render_position_doc_tab_html(doc),
        })
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


@router.get("/workspaces", response_class=HTMLResponse)
@router.get("/w/{workspace_slug}/workspaces", response_class=HTMLResponse)
def workspace_list(
    workspace_slug: str | None = None,
    owner: str = Query(default="any"),
    db: OrmSession = Depends(get_session),
):
    """The Workspace list view (build-spec §10.1) — what the Workspace nav item opens.

    `owner` is the filter chip: any | mine | not_mine. An unknown value falls back to
    'any' rather than erroring: a bad query string should not be able to 500 the page,
    and 'any' is the safe default because visibility is enforced in the query regardless
    of the chip.
    """
    if owner not in ("any", "mine", "not_mine"):
        owner = "any"
    try:
        product_id = products.resolve_product_id(db, workspace_slug)
        rows = repository.list_workspace_rows(
            db,
            product_id=product_id,
            member_id=members.current_member_id(db),
            owner=owner,
        )
        return HTMLResponse(
            render_workspace_list(db, rows, owner=owner, workspace_slug=workspace_slug)
        )
    except Exception as exc:
        return HTMLResponse(render_error(str(exc)), status_code=500)
