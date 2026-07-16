"""repository.py — basic CRUD for Questions/Outcomes (Phase 0.5 task 4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from pmqs.models import Member, NewsItem, Outcome, Question, Session, SessionMessage


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
    member_id: str | None = None,
) -> list[Question]:
    """Ranked Inbox list.

    By default excludes 'dismissed' and 'promoted' (they've left the Inbox) — only
    'proposed' and 'saved' remain. `include_all=True` returns every status (debug/API).
    Optional lens_tag / source filters (server-side, for the filter pills). Optional
    product_id scopes to one product's stream (the isolation boundary between
    products/PMs, see products.py); omitting it returns every product's questions,
    which existing single-product call sites still rely on until #56 threads a real
    product through routing.

    `member_id` scopes to one member's Inbox. THE INBOX IS ALWAYS MEMBER-SCOPED
    (build-spec §4 rule 5, §5) -- it is the private half of the product, and it stays
    private even as the Outcomes ledger opens up to the whole Product. Sharing happens
    when you OPEN a room (§4 rule 6), not while a question is still sitting in your
    inbox.
    """
    stmt = select(Question)
    if product_id is not None:
        stmt = stmt.where(Question.product_id == product_id)
    if member_id is not None:
        stmt = stmt.where(Question.author_member_id == member_id)
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


class OutcomeAlreadySharedError(Exception):
    """Raised when promoting an Outcome that the Product can already see.

    Promotion is one-way (build-spec §4 rule 4): private -> shared, never the reverse.
    There is no demote, so promoting something already shared isn't a harmless no-op --
    it's a sign the caller thinks it is hiding something that is in fact visible.
    """


def outcome_is_shared(db: OrmSession, outcome: Outcome) -> bool:
    """Resolve an Outcome's visibility (build-spec §4 rule 2 + §7 design note).

    Shared if its Session is shared, or if promoted_at IS NOT NULL. Computed, never
    stored: §7 forbids a `visibility` column here precisely because a denormalised copy
    drifts out of sync with the room it came from.

    An Outcome with no Session (created outside a room) has no visibility to inherit, so
    it follows the same default rooms do -- shared (§4 rule 1). Same for a dangling
    session_id: absence of a private room is not evidence of privacy.
    """
    if outcome.promoted_at is not None:
        return True
    if outcome.session_id is None:
        return True
    session = db.get(Session, outcome.session_id)
    if session is None:
        return True
    return session.visibility != "private"


def list_ledger_outcomes(
    db: OrmSession, *, product_id: str | None = None, member_id: str | None = None
) -> list[Outcome]:
    """The Outcomes ledger: every member's outcomes for this Product, newest first,
    filtered by §4's visibility resolution for `member_id`.

    This is the shared half of the product (build-spec §5) -- deliberately NOT scoped to
    the asking member. A colleague's outcomes are the whole point; the ledger is where
    the content network effect lives.

    Visibility is resolved in SQL rather than by filtering in Python so the ledger stays
    one query as it grows monotonically. An outcome is visible when ANY of:
      - it was promoted (§4 rule 3), or
      - it has no room to inherit privacy from, or
      - its room is shared, or
      - its room is private but `member_id` owns it (§3: visible only to its owner).
    """
    visible = [
        Outcome.promoted_at.is_not(None),
        Outcome.session_id.is_(None),
        Session.visibility != "private",
    ]
    if member_id is not None:
        # Only add the ownership escape when we actually know who is asking -- otherwise
        # `author_member_id == None` compiles to IS NULL and would expose every private
        # room that predates authorship backfill.
        visible.append(Session.author_member_id == member_id)

    stmt = select(Outcome).outerjoin(Session, Outcome.session_id == Session.id).where(or_(*visible))
    if product_id is not None:
        stmt = stmt.where(Outcome.product_id == product_id)
    stmt = stmt.order_by(Outcome.created_at.desc())
    return list(db.scalars(stmt))


def promote_outcome(db: OrmSession, outcome_id: str) -> Outcome | None:
    """Promote a private room's Outcome to the Product ledger (build-spec §4 rule 3).

    One of exactly two visibility actions in the whole product (the other being "create
    this room private"). Stamps promoted_at, which the visibility resolution reads as an
    override on the room's privacy.

    Raises OutcomeAlreadySharedError if the Product can already see it -- whether because
    its room is shared or because it was already promoted. Returns None if there's no
    such outcome.
    """
    o = db.get(Outcome, outcome_id)
    if o is None:
        return None
    if outcome_is_shared(db, o):
        raise OutcomeAlreadySharedError(
            f"outcome {outcome_id} is already visible to the Product; promotion is one-way"
        )
    o.promoted_at = _now()
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


def list_workspace_rows(
    db: OrmSession,
    *,
    product_id: str | None = None,
    member_id: str | None = None,
    owner: str = "any",
) -> list[dict[str, Any]]:
    """Rows for the Workspace list view (build-spec §10.1), newest-activity first.

    Each row: {session, name, owner_id, owner_name, last_modified, outcome_count, is_private}.

    `owner` is the filter chip: 'any' | 'mine' | 'not_mine', backed by author_member_id.

    PRIVATE WORKSPACES APPEAR ONLY FOR THEIR OWNER (§10.1) -- like an unshared Doc they
    are simply absent from everyone else's list, not greyed out or shown as "private".
    Their absence is the feature: a redacted row still tells you a colleague is working
    on something, which is exactly what private is for.

    DEVIATION FROM §10.1, flagged (§0): the spec sources "Last modified" from
    `session.updated_at`. THAT COLUMN DOES NOT EXIST -- §7's target state never adds it,
    so the doc specifies a column no work item creates. Rather than add one, this derives
    last-modified as max(session.created_at, latest message, latest outcome) in the same
    query. A stored updated_at would have to be touched on every write path that can
    modify a room (messages, outcomes, status, position doc); miss one and the column is
    silently wrong forever, which is the drift §7's design note warns about. Derived
    cannot drift. If a stored column is wanted for indexing later, that is a schema item
    with a backfill, not a quiet default here.
    """
    latest_message = (
        select(SessionMessage.session_id, func.max(SessionMessage.created_at).label("ts"))
        .group_by(SessionMessage.session_id)
        .subquery()
    )
    outcome_agg = (
        select(
            Outcome.session_id,
            func.max(Outcome.created_at).label("ts"),
            func.count(Outcome.id).label("n"),
        )
        .group_by(Outcome.session_id)
        .subquery()
    )
    stmt = (
        select(
            Session,
            Member.display_name,
            latest_message.c.ts,
            outcome_agg.c.ts,
            outcome_agg.c.n,
        )
        .outerjoin(Member, Session.author_member_id == Member.id)
        .outerjoin(latest_message, latest_message.c.session_id == Session.id)
        .outerjoin(outcome_agg, outcome_agg.c.session_id == Session.id)
    )
    if product_id is not None:
        stmt = stmt.where(Session.product_id == product_id)
    # §10.1: shared rooms, plus my own private ones. Same shape as the ledger's §4 filter.
    visible = [Session.visibility != "private"]
    if member_id is not None:
        visible.append(Session.author_member_id == member_id)
    stmt = stmt.where(or_(*visible))
    if owner == "mine" and member_id is not None:
        stmt = stmt.where(Session.author_member_id == member_id)
    elif owner == "not_mine" and member_id is not None:
        stmt = stmt.where(
            or_(Session.author_member_id != member_id, Session.author_member_id.is_(None))
        )

    rows = []
    for session, owner_name, msg_ts, out_ts, out_n in db.execute(stmt):
        rows.append(
            {
                "session": session,
                "name": session.topic or "(untitled)",
                "owner_id": session.author_member_id,
                "owner_name": owner_name or "Unknown",
                "last_modified": max(
                    x for x in (session.created_at, msg_ts, out_ts) if x
                ),
                "outcome_count": int(out_n or 0),
                "is_private": session.visibility == "private",
            }
        )
    # Default sort: last modified, descending (§10.1).
    rows.sort(key=lambda r: r["last_modified"], reverse=True)
    return rows
