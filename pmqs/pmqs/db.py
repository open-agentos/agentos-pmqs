"""db.py — SQLAlchemy engine + session factory against a local SQLite file.

SQLAlchemy Core/ORM so a Phase 5 swap to Postgres doesn't require a rewrite.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from pmqs import config


class Base(DeclarativeBase):
    pass


engine = create_engine(f"sqlite:///{config.DB_PATH}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from pmqs import models  # noqa: F401

    Base.metadata.create_all(engine)
    _apply_light_migrations()
    _backfill_default_workspace()
    _backfill_membership()


def _apply_light_migrations() -> None:
    """Prototype-grade additive migrations for SQLite (create_all won't add columns to
    existing tables). Adds any missing nullable columns introduced after initial ship.
    Safe/idempotent: checks PRAGMA table_info first.
    """
    from sqlalchemy import inspect, text

    additions = {
        "questions": [("origin_session_id", "TEXT"), ("workspace_id", "TEXT")],
        "sessions": [("workspace_id", "TEXT")],
        "outcomes": [("workspace_id", "TEXT")],
        "news_items": [("workspace_id", "TEXT")],
    }
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in additions.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, coltype in cols:
                if name not in have:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {coltype}'))
    # Note: `settings` (Setting) is NOT scoped to workspace_id yet -- its primary key
    # is a bare `key`, and rewriting that to a composite (workspace_id, key) key needs
    # a table rebuild rather than an additive column, which felt like more risk than
    # this pass warranted. LLM/context-budget config stays account-wide for now; the
    # per-product news watchlist follow-up is tracked as a known gap, not forgotten.


def _backfill_default_workspace() -> None:
    """Assign every pre-multi-product row (Question/Outcome/Session/NewsItem created
    before the Product/Workspace model existed, or since, via a code path that hasn't
    been threaded through to a specific workspace yet) to the account's default
    Workspace, creating one against config.AGENTOS_REPO if none exists yet.

    Idempotent and cheap to no-op: only touches rows where workspace_id IS NULL.
    """
    from sqlalchemy import update

    from pmqs import products
    from pmqs.models import NewsItem, Outcome, Question
    from pmqs.models import Session as SessionModel

    session = SessionLocal()
    try:
        pending = any(
            session.query(model).filter(model.workspace_id.is_(None)).first() is not None
            for model in (Question, Outcome, SessionModel, NewsItem)
        )
        if not pending:
            return
        ws = products.get_or_create_default_workspace(session)
        for model in (Question, Outcome, SessionModel, NewsItem):
            session.execute(
                update(model).where(model.workspace_id.is_(None)).values(workspace_id=ws.id)
            )
        session.commit()
    finally:
        session.close()


def _backfill_membership() -> None:
    """One Member row for the existing single-tenant user; one Membership per
    existing Product, role 'owner' (build-spec Wave 1 item 1 / §8 step 1).

    Idempotent: `members.get_or_create_default_member` reuses the existing stub
    Member, and `ensure_membership` no-ops if the (member, product) row already
    exists. Cheap to no-op when there are no products yet.
    """
    from pmqs import members as members_repo
    from pmqs.models import Product

    session = SessionLocal()
    try:
        products = list(session.query(Product).all())
        if not products:
            return
        member = members_repo.get_or_create_default_member(session)
        for product in products:
            members_repo.ensure_membership(session, member=member, product=product, role="owner")
    finally:
        session.close()


def get_session():
    """Yield a session (FastAPI dependency friendly)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
