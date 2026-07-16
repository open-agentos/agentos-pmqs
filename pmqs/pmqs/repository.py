"""repository.py — basic CRUD for Questions/Outcomes (Phase 0.5 task 4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from pmqs.models import NewsItem, Outcome, Question, Session, SessionMessage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_workspace_id(db: OrmSession) -> str:
    """Fall back to the account's default Workspace when a caller doesn't specify one.

    Keeps every existing call site (pre-#56 routing work) working unchanged while new
    rows still land in a real Workspace rather than NULL. Once routes thread a real
    workspace_id through explicitly (see #56), this fallback simply stops being hit.
    """
    from pmqs import products

    return products.get_or_create_default_workspace(db).id


# --- Questions ---
def create_question(
    db: OrmSession,
    *,
    title: str,
    source: str,
    description: str | None = None,
    lens_tags: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    status: str = "proposed",
    score: float | None = None,
    score_dims: dict[str, Any] | None = None,
    origin_session_id: str | None = None,
    workspace_id: str | None = None,
) -> Question:
    q = Question(
        workspace_id=workspace_id or _resolve_workspace_id(db),
        title=title,
        source=source,
        description=description,
        lens_tags=json.dumps(lens_tags or []),
        evidence=json.dumps(evidence or []),
        status=status,
        score=score,
        score_dims=json.dumps(score_dims) if score_dims is not None else None,
        origin_session_id=origin_session_id,
    )
    db.add(q)
    db.commit()
    return q


def get_question(db: OrmSession, qid: str) -> Question | None:
    return db.get(Question, qid)


def list_questions(
    db: OrmSession,
    *,
    lens_tag: str | None = None,
    source: str | None = None,
    include_all: bool = False,
    workspace_id: str | None = None,
) -> list[Question]:
    """Ranked Inbox list.

    By default excludes 'dismissed' and 'promoted' (they've left the Inbox) — only
    'proposed' and 'saved' remain. `include_all=True` returns every status (debug/API).
    Optional lens_tag / source filters (server-side, for the filter pills). Optional
    workspace_id scopes to one product's stream (the isolation boundary between
    products/PMs, see products.py); omitting it returns every workspace's questions,
    which existing single-workspace call sites still rely on until #56 threads a real
    workspace through routing.
    """
    stmt = select(Question)
    if workspace_id is not None:
        stmt = stmt.where(Question.workspace_id == workspace_id)
    rows = list(db.scalars(stmt))
    if not include_all:
        rows = [q for q in rows if q.status in ("proposed", "saved")]
    if lens_tag:
        rows = [q for q in rows if lens_tag in q.lens_tags_list]
    if source:
        rows = [q for q in rows if q.source == source]
    # Ranked by score desc; unscored (None) sort last.
    rows.sort(key=lambda q: (q.score is None, -(q.score or 0.0)))
    return rows


def list_session_proposed(db: OrmSession, session_id: str) -> list[Question]:
    """Proposed questions produced by a specific war-room session's lens run (B6)."""
    rows = list(
        db.scalars(
            select(Question)
            .where(Question.origin_session_id == session_id)
            .where(Question.status == "proposed")
        )
    )
    rows.sort(key=lambda q: (q.score is None, -(q.score or 0.0)))
    return rows


def update_question_status(db: OrmSession, qid: str, status: str) -> Question | None:
    q = db.get(Question, qid)
    if q is None:
        return None
    q.status = status
    q.updated_at = _now()
    db.commit()
    return q


def set_question_score(db: OrmSession, qid: str, score: float, dims: dict[str, Any]) -> Question | None:
    q = db.get(Question, qid)
    if q is None:
        return None
    q.score = score
    q.score_dims = json.dumps(dims)
    q.updated_at = _now()
    db.commit()
    return q


# --- Sessions (Phase 2 war-room) ---
def open_session(db: OrmSession, *, topic: str | None = None,
                 question_id: str | None = None, parent_id: str | None = None,
                 workspace_id: str | None = None) -> Session:
    s = Session(
        topic=topic, question_id=question_id, parent_id=parent_id, status="open",
        workspace_id=workspace_id or _resolve_workspace_id(db),
    )
    db.add(s)
    db.commit()
    return s


def get_session_row(db: OrmSession, sid: str) -> Session | None:
    return db.get(Session, sid)


def find_open_session_for_question(db: OrmSession, question_id: str) -> Session | None:
    """Most-recent OPEN, non-branch session anchored to this question, if any.

    Used so 're-open the war-room for question X' reuses the existing session (and its
    Position Doc / conversation) instead of spawning a fresh empty one each time.
    """
    stmt = (
        select(Session)
        .where(Session.question_id == question_id)
        .where(Session.status == "open")
        .where(Session.parent_id.is_(None))
        .order_by(Session.created_at.desc())
    )
    return db.scalars(stmt).first()


def close_session(db: OrmSession, sid: str) -> Session | None:
    s = db.get(Session, sid)
    if s is None:
        return None
    s.status = "closed"
    s.closed_at = _now()
    db.commit()
    return s


def set_position_doc(db: OrmSession, sid: str, doc: dict[str, Any]) -> Session | None:
    s = db.get(Session, sid)
    if s is None:
        return None
    s.position_doc = json.dumps(doc)
    db.commit()
    return s


def add_message(db: OrmSession, session_id: str, *, role: str, content: str) -> SessionMessage:
    m = SessionMessage(session_id=session_id, role=role, content=content)
    db.add(m)
    db.commit()
    return m


def list_messages(db: OrmSession, session_id: str) -> list[SessionMessage]:
    return list(
        db.scalars(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        )
    )


# --- Outcomes ---
def create_outcome(
    db: OrmSession,
    *,
    type: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    github_ref: str | None = None,
    workspace_id: str | None = None,
) -> Outcome:
    # Policies must never sync to GitHub (product-design.md). Enforce here.
    if type == "policy" and github_ref is not None:
        raise ValueError("Policy outcomes must never carry a github_ref")
    o = Outcome(
        type=type,
        payload=json.dumps(payload),
        session_id=session_id,
        github_ref=github_ref,
        workspace_id=workspace_id or _resolve_workspace_id(db),
    )
    db.add(o)
    db.commit()
    return o


def list_outcomes(db: OrmSession, *, workspace_id: str | None = None) -> list[Outcome]:
    stmt = select(Outcome)
    if workspace_id is not None:
        stmt = stmt.where(Outcome.workspace_id == workspace_id)
    return list(db.scalars(stmt))


def list_durable_outcomes(db: OrmSession, *, active_only: bool = True, workspace_id: str | None = None) -> list[Outcome]:
    """Durable (policy|document|meeting) outcomes, newest first. Feeds the context-feed.

    workspace_id matters most here: Policies must never leak across products (or
    across PMs sharing a product) into another workspace's agent context.
    """
    from pmqs.outcomes.types import DURABLE_TYPES

    stmt = select(Outcome).where(Outcome.type.in_(DURABLE_TYPES))
    if active_only:
        stmt = stmt.where(Outcome.active.is_(True))
    if workspace_id is not None:
        stmt = stmt.where(Outcome.workspace_id == workspace_id)
    stmt = stmt.order_by(Outcome.created_at.desc())
    return list(db.scalars(stmt))


def deactivate_outcome(db: OrmSession, outcome_id: str) -> Outcome | None:
    o = db.get(Outcome, outcome_id)
    if o is None:
        return None
    o.active = False
    db.commit()
    return o


def outcome_payload(outcome: Outcome) -> dict[str, Any]:
    try:
        return json.loads(outcome.payload or "{}")
    except json.JSONDecodeError:
        return {}


# --- News items (Phase 4 raw staging store) ---
def create_news_item(
    db: OrmSession,
    *,
    url: str,
    title: str = "",
    source_label: str = "",
    summary: str | None = None,
    published_at: str | None = None,
    workspace_id: str | None = None,
) -> NewsItem | None:
    """Create a raw news item. Dedup by URL: returns None if the URL already exists."""
    existing = db.scalars(select(NewsItem).where(NewsItem.url == url)).first()
    if existing is not None:
        return None
    item = NewsItem(
        url=url, title=title, source_label=source_label,
        summary=summary, published_at=published_at,
        workspace_id=workspace_id or _resolve_workspace_id(db),
    )
    db.add(item)
    db.commit()
    return item


def list_news_items(db: OrmSession, *, unprocessed_only: bool = False, workspace_id: str | None = None) -> list[NewsItem]:
    stmt = select(NewsItem)
    if unprocessed_only:
        stmt = stmt.where(NewsItem.processed.is_(False))
    if workspace_id is not None:
        stmt = stmt.where(NewsItem.workspace_id == workspace_id)
    stmt = stmt.order_by(NewsItem.fetched_at.desc())
    return list(db.scalars(stmt))


def mark_news_processed(db: OrmSession, item_ids: list[str]) -> None:
    for iid in item_ids:
        item = db.get(NewsItem, iid)
        if item is not None:
            item.processed = True
    db.commit()
