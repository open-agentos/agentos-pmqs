"""db.py — SQLAlchemy engine + session factory against a local SQLite file.

SQLAlchemy Core/ORM so a Phase 5 swap to Postgres doesn't require a rewrite.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

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
    _fold_news_config_onto_default_product()
    _backfill_session_authorship()
    _backfill_outcome_authorship()
    _backfill_question_authorship()


def _apply_light_migrations() -> None:
    """Prototype-grade additive migrations for SQLite (create_all won't add columns to
    existing tables). Adds any missing nullable columns introduced after initial ship.
    Safe/idempotent: checks PRAGMA table_info first.
    """
    from sqlalchemy import inspect, text

    additions = {
        "questions": [
            ("origin_session_id", "TEXT"),
            ("product_id", "TEXT"),
            ("author_member_id", "TEXT"),
        ],
        "sessions": [
            ("product_id", "TEXT"),
            ("author_member_id", "TEXT"),
            ("visibility", "TEXT NOT NULL DEFAULT 'shared'"),
            ("close_reason", "TEXT"),
        ],
        "outcomes": [
            ("product_id", "TEXT"),
            ("author_member_id", "TEXT"),
            ("promoted_at", "TEXT"),
            ("retired_at", "TEXT"),
            ("superseded_by_outcome_id", "TEXT"),
        ],
        "news_items": [("product_id", "TEXT")],
        "products": [
            ("slug", "TEXT"),
            ("nickname", "TEXT"),
            ("lens_weights", "TEXT"),
            ("archived", "BOOLEAN DEFAULT 0"),
            ("news_config", "TEXT"),
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
        if "outcomes" in existing_tables:
            _migrate_outcome_active_to_retired_at(conn)
        if "products" in existing_tables:
            _migrate_products_relax_repo_notnull(conn)


def _migrate_outcome_active_to_retired_at(conn) -> None:
    """One-time: retire the `outcomes.active` BOOLEAN in favour of `retired_at`.

    build-spec §7 makes `retired_at IS NULL` the active predicate and warns against a
    denormalised second copy of state that can drift. `active` predates the spec and
    now says the same thing in a second place, so it is folded in and dropped rather
    than left to disagree with retired_at. (§0: the doc was written from a description
    of the schema and does not mention `active` at all -- flagged, folded, not forced.)

    Dropping is not optional housekeeping: `active` is NOT NULL with a Python-side
    default, so the moment the ORM model stops emitting it every INSERT on an existing
    DB would fail the NOT NULL constraint. Requires SQLite >= 3.35 (ALTER TABLE DROP
    COLUMN); the project targets 3.12/ubuntu-latest, which ships 3.45.

    Idempotent: no-ops once the column is gone. Fresh DBs never see it -- create_all
    builds the table from the model, which has no `active` column.
    """
    from sqlalchemy import text

    have = {row[1] for row in conn.execute(text("PRAGMA table_info(outcomes)")).fetchall()}
    if "active" not in have or "retired_at" not in have:
        return
    # Deactivated rows become retired rows. The real retirement instant was never
    # recorded, so stamp migration-time: created_at would falsely imply the outcome was
    # never active at all, which is worse than a known-approximate timestamp.
    conn.execute(
        text("UPDATE outcomes SET retired_at = :now WHERE active = 0 AND retired_at IS NULL"),
        {"now": datetime.now(timezone.utc).isoformat()},
    )
    conn.execute(text("ALTER TABLE outcomes DROP COLUMN active"))


def _migrate_products_relax_repo_notnull(conn) -> None:
    """Relax products.org / products.repo from NOT NULL to nullable.

    GitHub stops being a Product's identity (docs/build-spec-optional-repo-onramp.md
    §4): a product can be website-only, with org/repo NULL and a repo attached later.
    SQLite has no ALTER COLUMN to drop NOT NULL, so this rebuilds the table (the standard
    swap: create relaxed twin -> INSERT..SELECT -> drop -> rename), preserving every
    other column exactly as reflected via PRAGMA rather than hard-coding the schema.

    Idempotent: no-ops once org and repo are already nullable. Fresh DBs never see it --
    create_all builds the nullable schema straight from the model.

    Safe to DROP/rename `products` despite the product_id foreign keys on other tables:
    this app never enables `PRAGMA foreign_keys` (SQLite's default is OFF), so those FKs
    are declarative-only, and after the rename the table name is restored so every
    reference stays valid. SQLite also treats NULLs as distinct in UNIQUE(org, repo), so
    the constraint is recreated unchanged and website-only rows don't collide.
    """
    from sqlalchemy import text

    info = conn.execute(text("PRAGMA table_info(products)")).fetchall()
    if not info:
        return
    by_name = {row[1]: row for row in info}  # row = (cid, name, type, notnull, dflt, pk)
    if "org" not in by_name or "repo" not in by_name:
        return
    if by_name["org"][3] == 0 and by_name["repo"][3] == 0:
        return  # already nullable -- nothing to do

    col_defs, col_names = [], []
    for _cid, name, coltype, notnull, dflt, pk in info:
        col_names.append(name)
        parts = [f'"{name}"', coltype or "TEXT"]
        if pk:
            parts.append("PRIMARY KEY")
        if notnull and name not in ("org", "repo"):  # force org/repo nullable, keep the rest
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))
    col_defs.append('CONSTRAINT uq_products_org_repo UNIQUE ("org", "repo")')
    col_defs.append('CONSTRAINT uq_products_slug UNIQUE ("slug")')

    names_sql = ", ".join(f'"{n}"' for n in col_names)
    conn.execute(text("DROP TABLE IF EXISTS products_new"))
    conn.execute(text(f'CREATE TABLE products_new ({", ".join(col_defs)})'))
    conn.execute(text(f"INSERT INTO products_new ({names_sql}) SELECT {names_sql} FROM products"))
    conn.execute(text("DROP TABLE products"))
    conn.execute(text("ALTER TABLE products_new RENAME TO products"))


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


def _fold_news_config_onto_default_product() -> None:
    """One-time fold (#96): the watchlist/queries/product_profile used to live in the
    account-wide `news` settings row. They belong to a Product now. Move them onto the
    account's default product rather than dropping them -- a PM who configured a
    watchlist last week should not open Settings to find it gone.

    Idempotent: skips once the settings row no longer carries the old keys, and never
    overwrites a Product that already has news_config.
    """
    from pmqs import products as products_repo
    from pmqs import settings as settings_mod
    from pmqs.models import Setting

    with SessionLocal() as session:
        row = session.get(Setting, "news")
        if row is None:
            return
        try:
            stored = json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return
        legacy = {k: stored[k] for k in ("watchlist", "queries", "product_profile") if k in stored}
        if not legacy:
            return  # already folded

        product = products_repo.get_or_create_default_product(session)
        if not product.news_config:
            products_repo.set_news_config(
                session, product,
                watchlist=legacy.get("watchlist") or {},
                queries=legacy.get("queries") or [],
                product_profile=legacy.get("product_profile") or "",
            )
        # Drop the old keys so the fold doesn't run again, and so the account row can't
        # keep shadowing the Product's copy.
        for key in ("watchlist", "queries", "product_profile"):
            stored.pop(key, None)
        row.value = json.dumps(stored)
        session.commit()


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


def _backfill_question_authorship() -> None:
    """Every existing Question authored to the account's default Member (build-spec §7:
    "ALTERED question + author_member_id"). Same shape as the Session/Outcome backfills.

    Idempotent: only touches rows where author_member_id IS NULL.
    """
    from sqlalchemy import update

    from pmqs import members as members_repo
    from pmqs.models import Member, Question

    session = SessionLocal()
    try:
        pending = session.query(Question).filter(Question.author_member_id.is_(None)).first() is not None
        if not pending:
            return
        member = session.query(Member).first()
        if member is None:
            member = members_repo.get_or_create_default_member(session)
        session.execute(
            update(Question)
            .where(Question.author_member_id.is_(None))
            .values(author_member_id=member.id)
        )
        session.commit()
    finally:
        session.close()


def _backfill_outcome_authorship() -> None:
    """Every existing Outcome authored to the account's default Member (build-spec §7
    backfill note; Wave 1 item 4). Same shape as _backfill_session_authorship.

    Idempotent: only touches rows where author_member_id IS NULL. No-ops if there is no
    Member yet -- _backfill_membership runs first in init_db and creates one whenever a
    Product exists.

    Deliberately NOT inherited from the outcome's session author: single-tenant they are
    the same member, and once Phase 5 lands multiple members an outcome's author is
    whoever produced it, not whoever opened the room. Guessing that now would bake in a
    wrong rule that reads as deliberate later.
    """
    from sqlalchemy import update

    from pmqs import members as members_repo
    from pmqs.models import Member, Outcome

    session = SessionLocal()
    try:
        pending = session.query(Outcome).filter(Outcome.author_member_id.is_(None)).first() is not None
        if not pending:
            return
        member = session.query(Member).first()
        if member is None:
            member = members_repo.get_or_create_default_member(session)
        session.execute(
            update(Outcome)
            .where(Outcome.author_member_id.is_(None))
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
