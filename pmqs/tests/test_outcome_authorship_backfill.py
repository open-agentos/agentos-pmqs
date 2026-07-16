"""Tests for the outcome-authorship backfill and the active -> retired_at column
migration in db.init_db (Shared Outcomes build-spec, Wave 1 item 4 / §7, §8 step 4).
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs.models import Member, Outcome


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


@pytest.fixture
def db_module(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(
        db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True)
    )
    return db_module


def test_backfill_outcome_authorship_assigns_default_member(db_module, engine):
    db_module.Base.metadata.create_all(engine)

    seed = db_module.SessionLocal()
    seed.add(Outcome(type="policy", payload="{}"))  # no author_member_id, pre-migration shape
    seed.commit()
    seed.close()

    db_module._backfill_outcome_authorship()

    check = db_module.SessionLocal()
    try:
        outcome = check.query(Outcome).first()
        assert outcome.author_member_id is not None
        assert check.query(Member).count() == 1
    finally:
        check.close()

    # Idempotent: running again doesn't reassign or duplicate members.
    db_module._backfill_outcome_authorship()
    check2 = db_module.SessionLocal()
    try:
        assert check2.query(Member).count() == 1
    finally:
        check2.close()


def test_backfill_outcome_authorship_noop_when_no_outcomes(db_module, engine):
    db_module.Base.metadata.create_all(engine)

    db_module._backfill_outcome_authorship()

    check = db_module.SessionLocal()
    try:
        assert check.query(Member).count() == 0
    finally:
        check.close()


# --- active -> retired_at column migration ---
# The pre-migration `outcomes` table, as it exists in Matt's dogfood DB today: an
# `active BOOLEAN NOT NULL` and none of the Wave 1 item 4 columns. Built by hand rather
# than via create_all, because create_all now builds the POST-migration shape.
PRE_MIGRATION_OUTCOMES_DDL = """
CREATE TABLE outcomes (
    id TEXT NOT NULL PRIMARY KEY,
    product_id TEXT,
    type TEXT NOT NULL,
    session_id TEXT,
    payload TEXT NOT NULL,
    github_ref TEXT,
    active BOOLEAN NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _seed_pre_migration_outcomes(engine):
    with engine.begin() as conn:
        conn.execute(text(PRE_MIGRATION_OUTCOMES_DDL))
        conn.execute(
            text(
                "INSERT INTO outcomes (id, type, payload, active, created_at) VALUES "
                "('live', 'policy', '{}', 1, '2026-01-01T00:00:00+00:00'), "
                "('dead', 'policy', '{}', 0, '2026-01-02T00:00:00+00:00')"
            )
        )


def _columns(engine, table):
    with engine.begin() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def test_migration_folds_active_into_retired_at_and_drops_the_column(db_module, engine):
    _seed_pre_migration_outcomes(engine)

    db_module._apply_light_migrations()

    assert "active" not in _columns(engine, "outcomes"), "stored `active` must not survive"
    assert {"retired_at", "promoted_at", "superseded_by_outcome_id", "author_member_id"} <= _columns(
        engine, "outcomes"
    )

    check = db_module.SessionLocal()
    try:
        live = check.get(Outcome, "live")
        dead = check.get(Outcome, "dead")
        # active=1 stays active; active=0 becomes retired.
        assert live.retired_at is None and live.active is True
        assert dead.retired_at is not None and dead.active is False
        # Retired, but not superseded -- nothing replaced it (build-spec §7's third state).
        assert dead.superseded_by_outcome_id is None
        # Migration-time, not created_at: created_at would falsely imply it was never active.
        assert dead.retired_at > dead.created_at
    finally:
        check.close()


def test_migration_is_idempotent_and_inserts_still_work_after_it(db_module, engine):
    _seed_pre_migration_outcomes(engine)

    db_module._apply_light_migrations()
    retired_first = db_module.SessionLocal().get(Outcome, "dead").retired_at

    db_module._apply_light_migrations()  # second run must no-op, not re-stamp

    check = db_module.SessionLocal()
    try:
        assert check.get(Outcome, "dead").retired_at == retired_first
    finally:
        check.close()

    # The reason the column has to be DROPped rather than just ignored: it was NOT NULL
    # with a Python-side default, so an ORM insert that no longer mentions it would fail
    # the constraint on every existing DB.
    insert = db_module.SessionLocal()
    try:
        insert.add(Outcome(id="fresh", type="document", payload="{}", created_at="2026-01-03T00:00:00+00:00"))
        insert.commit()
        assert insert.get(Outcome, "fresh").active is True
    finally:
        insert.close()
