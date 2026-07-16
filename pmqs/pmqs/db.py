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
    _backfill_default_product()
    _backfill_membership()
    _backfill_session_authorship()


def _apply_light_migrations() -> None:
    """Prototype-grade additive migrations for SQLite (create_all won't add columns to
    existing tables). Adds any missing nullable columns introduced after initial ship.
    Safe/idempotent: checks PRAGMA table_info first.
    """
    from sqlalchemy import inspect, text

    additions = {
        "questions": [("origin_session_id", "TEXT"), ("product_id", "TEXT")],
        "sessions": [
            ("product_id", "TEXT"),
            ("author_member_id", "TEXT"),
            ("visibility", "TEXT NOT NULL DEFAULT 'shared'"),
        ],
        "outcomes": [("product_id", "TEXT")],
        "news_items": [("product_id", "TEXT")],
        "products": [
            ("slug", "TEXT"),
            ("nickname", "TEXT"),
            ("lens_weights", "TEXT"),
            ("archived", "BOOLEAN DEFAULT 0"),
        ],
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
        # Fold-forward: rows created before this migration have workspace_id on the
        # hosted-store tables (pre-#8-step-2 schema) but no product_id yet. If the old
        # `workspaces` table is still present, copy each row's product_id through
        # its old workspace_id so existing data survives the rename instead of
        # silently orphaning (build-spec §8 step 2 -- inspected before dropping).
        if "workspaces" in existing_tables:
            _fold_workspace_into_product(conn, insp)


def _fold_workspace_into_product(conn, insp) -> None:
    """One-time fold: copy each `workspaces` row's slug/nickname/lens_weights/archived
    onto its `product` row, repoint every workspace_id-carrying row at that product_id,
    then drop the now-empty `workspaces` table. Runs once per DB (skips if
    `workspaces` is already gone -- see caller).
    """
    from sqlalchemy import text

    ws_cols = {c["name"] for c in insp.get_columns("workspaces")}
    if not {"id", "product_id", "slug"}.issubset(ws_cols):
        return  # unexpected shape; don't guess, leave for manual inspection
    rows = conn.execute(text("SELECT id, product_id, slug, nickname, lens_weights, archived FROM workspaces")).fetchall()
    for ws_id, product_id, slug, nickname, lens_weights, archived in rows:
        if product_id is None:
            continue
        conn.execute(
            text(
                "UPDATE products SET slug = COALESCE(slug, :slug), "
                "nickname = COALESCE(nickname, :nickname), "
                "lens_weights = COALESCE(lens_weights, :lens_weights), "
                "archived = :archived WHERE id = :pid"
            ),
            {"slug": slug, "nickname": nickname, "lens_weights": lens_weights,
             "archived": bool(archived), "pid": product_id},
        )
        for table in ("questions", "sessions", "outcomes", "news_items"):
            table_cols = {c["name"] for c in insp.get_columns(table)}
            if "workspace_id" in table_cols:
                conn.execute(
                    text(f"UPDATE {table} SET product_id = :pid WHERE workspace_id = :wid AND product_id IS NULL"),
                    {"pid": product_id, "wid": ws_id},
                )
    conn.execute(text("DROP TABLE workspaces"))


def _backfill_default_product() -> None:
    """Assign every pre-multi-product row (Question/Outcome/Session/NewsItem created
    before the Product model existed, or since, via a code path that hasn't been
    threaded through to a specific product yet) to the account's default Product,
    creating one against config.AGENTOS_REPO if none exists yet.

    Idempotent and cheap to no-op: only touches rows where product_id IS NULL.
    """
    from sqlalchemy import update

    from pmqs import products
    from pmqs.models import NewsItem, Outcome, Question
    from pmqs.models import Session as SessionModel

    session = SessionLocal()
    try:
        pending = any(
            session.query(model).filter(model.product_id.is_(None)).first() is not None
            for model in (Question, Outcome, SessionModel, NewsItem)
        )
        if not pending:
            return
        product = products.get_or_create_default_product(session)
        for model in (Question, Outcome, SessionModel, NewsItem):
            session.execute(
                update(model).where(model.product_id.is_(None)).values(product_id=product.id)
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


def _backfill_session_authorship() -> None:
    """Every existing Session authored to the account's default Member (build-spec
    §7 backfill note; Wave 1 item 3). Idempotent: only touches rows where
    author_member_id IS NULL. No-ops if there is no Member yet (nothing to backfill
    onto -- _backfill_membership runs first in init_db and creates one whenever a
    Product exists).
    """
    from sqlalchemy import update

    from pmqs import members as members_repo
    from pmqs.models import Member, Session as SessionModel

    session = SessionLocal()
    try:
        pending = session.query(SessionModel).filter(SessionModel.author_member_id.is_(None)).first() is not None
        if not pending:
            return
        member = session.query(Member).first()
        if member is None:
            member = members_repo.get_or_create_default_member(session)
        session.execute(
            update(SessionModel)
            .where(SessionModel.author_member_id.is_(None))
            .values(author_member_id=member.id)
        )
        session.commit()
    finally:
        session.close()


def get_session():
    """Yield a session (FastAPI dependency friendly)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
