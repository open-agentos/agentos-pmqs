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


def _apply_light_migrations() -> None:
    """Prototype-grade additive migrations for SQLite (create_all won't add columns to
    existing tables). Adds any missing nullable columns introduced after initial ship.
    Safe/idempotent: checks PRAGMA table_info first.
    """
    from sqlalchemy import inspect, text

    additions = {
        "questions": [("origin_session_id", "TEXT")],
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


def get_session():
    """Yield a session (FastAPI dependency friendly)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
