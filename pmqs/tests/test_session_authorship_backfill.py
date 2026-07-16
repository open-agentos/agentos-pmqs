"""Tests for the session-authorship backfill in db.init_db (Shared Outcomes build-spec,
Wave 1 item 3 / §8 step 3 acceptance)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs.models import Member, Session as SessionModel


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    yield eng
    eng.dispose()


def test_backfill_session_authorship_assigns_default_member(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))
    db_module.Base.metadata.create_all(engine)

    seed = db_module.SessionLocal()
    seed.add(SessionModel(topic="legacy session"))  # no author_member_id, pre-migration shape
    seed.commit()
    seed.close()

    db_module._backfill_session_authorship()

    check = db_module.SessionLocal()
    try:
        sess = check.query(SessionModel).first()
        assert sess.author_member_id is not None
        assert check.query(Member).count() == 1
    finally:
        check.close()

    # Idempotent: running again doesn't reassign or duplicate members.
    db_module._backfill_session_authorship()
    check2 = db_module.SessionLocal()
    try:
        assert check2.query(Member).count() == 1
    finally:
        check2.close()


def test_backfill_session_authorship_noop_when_no_sessions(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))
    db_module.Base.metadata.create_all(engine)

    db_module._backfill_session_authorship()

    check = db_module.SessionLocal()
    try:
        assert check.query(Member).count() == 0
    finally:
        check.close()
