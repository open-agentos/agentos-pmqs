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


def _resolve_product_id(db: OrmSession) -> str:
    """Fall back to the account's default Product when a caller doesn't specify one.

    Keeps every existing call site (pre-#56 routing work) working unchanged while new
    rows still land in a real Product rather than NULL. Once routes thread a real
    product_id through explicitly (see #56), this fallback simply stops being hit.
    """
    from pmqs import products

    return products.get_or_create_default_product(db).id


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
    product_id: str | None = None,
    author_member_id: str | None = None,
) -> Question:
    """Create a Question (an inbox item).

    `author_member_id` is whose inbox it lands in, and defaults to the account's stub
    Member (single-tenant until Phase 5 auth), mirroring open_session()/create_outcome().
    This holds whether the question was raised by the PM, the lens pass, or news: the
    Inbox is always member-scoped (build-spec §4 rule 5), so every question has an owner.
    """
    from pmqs import members as members_repo

    q = Question(
        product_id=product_id or _resolve_product_id(db),
        author_member_id=author_member_id or members_repo.get_or_create_default_member(db).id,
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
    product_id: str | None = None,
) -> list[Question]:
    """Ranked Inbox list.

    By default excludes 'dismissed' and 'promoted' (they've left the Inbox) — only
    'proposed' and 'saved' remain. `include_all=True` returns every status (debug/API).
    Optional lens_tag / source filters (server-side, for the filter pills). Optional
    product_id scopes to one product's stream (the isolation boundary between
    products/PMs, see products.py); omitting it returns every product's questions,
    which existing single-product call sites still rely on until #56 threads a real
    product through routing.
    """
    stmt = select(Question)
    if product_id is not None:
        stmt = stmt.where(Question.product_id == product_id)
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
                 product_id: str | None = None, author_member_id: str | None = None,
                 visibility: str = "shared") -> Session:
    """Open a new war-room Session.

    `author_member_id` defaults to the account's stub Member if not given (single-
    tenant until Phase 5 auth -- see members.get_or_create_default_member).
    `visibility` defaults to 'shared' per build-spec §4 rule 1 ("A Workspace is
    shared by default; it may be created private").
    """
    from pmqs import members as members_repo

    s = Session(
        topic=topic, question_id=question_id, parent_id=parent_id, status="open",
        product_id=product_id or _resolve_product_id(db),
        author_member_id=author_member_id or members_repo.get_or_create_default_member(db).id,
        visibility=visibility,
    )
    db.add(s)
    db.commit()
    return s


def get_session_row(db: OrmSession, sid: str) -> Session | None:
    return db.get(Session, sid)


def get_visible_session_row(db: OrmSession, sid: str, *, member_id: str | None) -> Session | None:
    """Fetch a Session enforcing build-spec §4's visibility rule: a private session
    is retrievable only by its author. Returns None if the session doesn't exist OR
    exists but is private and `member_id` isn't its author -- callers can't tell the
    two apart, which is the point (no leaking existence of a private room).
    """
    s = db.get(Session, sid)
    if s is None:
        return None
    if s.visibility == "private" and s.author_member_id != member_id:
        return None
    return s


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
    product_id: str | None = None,
    author_member_id: str | None = None,
) -> Outcome:
    """Record an Outcome.

    `author_member_id` defaults to the account's stub Member if not given (single-tenant
    until Phase 5 auth), mirroring open_session(). New outcomes are active
    (retired_at IS NULL) and unpromoted (promoted_at IS NULL) -- promotion is an
    explicit act, see build-spec §4 rule 3.
    """
    from pmqs import members as members_repo

    # Policies must never sync to GitHub (product-design.md). Enforce here.
    if type == "policy" and github_ref is not None:
        raise ValueError("Policy outcomes must never carry a github_ref")
    o = Outcome(
        type=type,
        payload=json.dumps(payload),
        session_id=session_id,
        github_ref=github_ref,
        product_id=product_id or _resolve_product_id(db),
        author_member_id=author_member_id or members_repo.get_or_create_default_member(db).id,
    )
    db.add(o)
    db.commit()
    return o


def list_outcomes(db: OrmSession, *, product_id: str | None = None) -> list[Outcome]:
    stmt = select(Outcome)
    if product_id is not None:
        stmt = stmt.where(Outcome.product_id == product_id)
    return list(db.scalars(stmt))


def list_durable_outcomes(db: OrmSession, *, active_only: bool = True, product_id: str | None = None) -> list[Outcome]:
    """Durable (policy|document|meeting) outcomes, newest first. Feeds the context-feed.

    product_id matters most here: Policies must never leak across products (or
    across PMs sharing a product) into another product's agent context.
    """
    from pmqs.outcomes.types import DURABLE_TYPES

    stmt = select(Outcome).where(Outcome.type.in_(DURABLE_TYPES))
    if active_only:
        # build-spec §7: `retired_at IS NULL` is THE active predicate. This is the guard
        # against landfill -- a shared ledger grows monotonically, and without lifecycle
        # the context pool fills with contradictory standing rules and the system gets
        # dumber as the team gets busier.
        stmt = stmt.where(Outcome.retired_at.is_(None))
    if product_id is not None:
        stmt = stmt.where(Outcome.product_id == product_id)
    stmt = stmt.order_by(Outcome.created_at.desc())
    return list(db.scalars(stmt))


def deactivate_outcome(
    db: OrmSession, outcome_id: str, *, superseded_by_outcome_id: str | None = None
) -> Outcome | None:
    """Retire an Outcome, optionally naming the Outcome that replaces it.

    Stamps retired_at, which is the only thing that makes an outcome inactive
    (build-spec §7). Passing `superseded_by_outcome_id` distinguishes the spec's two
    retired states -- superseded (replaced by outcome N) from retired-without-
    replacement (just no longer stands) -- without a status enum to migrate later.

    Idempotent on retired_at: re-retiring an already-retired outcome keeps the original
    timestamp rather than moving it, so the ledger's history doesn't drift on a double
    click. A later supersede can still name the replacement.
    """
    o = db.get(Outcome, outcome_id)
    if o is None:
        return None
    if o.retired_at is None:
        o.retired_at = _now()
    if superseded_by_outcome_id is not None:
        o.superseded_by_outcome_id = superseded_by_outcome_id
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
    product_id: str | None = None,
) -> NewsItem | None:
    """Create a raw news item. Dedup by URL: returns None if the URL already exists."""
    existing = db.scalars(select(NewsItem).where(NewsItem.url == url)).first()
    if existing is not None:
        return None
    item = NewsItem(
        url=url, title=title, source_label=source_label,
        summary=summary, published_at=published_at,
        product_id=product_id or _resolve_product_id(db),
    )
    db.add(item)
    db.commit()
    return item


def list_news_items(db: OrmSession, *, unprocessed_only: bool = False, product_id: str | None = None) -> list[NewsItem]:
    stmt = select(NewsItem)
    if unprocessed_only:
        stmt = stmt.where(NewsItem.processed.is_(False))
    if product_id is not None:
        stmt = stmt.where(NewsItem.product_id == product_id)
    stmt = stmt.order_by(NewsItem.fetched_at.desc())
    return list(db.scalars(stmt))


def mark_news_processed(db: OrmSession, item_ids: list[str]) -> None:
    for iid in item_ids:
        item = db.get(NewsItem, iid)
        if item is not None:
            item.processed = True
    db.commit()
