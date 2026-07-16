"""Tests for the members backfill in db.init_db (Shared Outcomes build-spec, Wave 1
item 1 / §8 step 1 acceptance: 'one member; one membership per product with role
owner; existing rows authored to it').
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products
from pmqs.models import Member, Membership


@pytest.fixture
def engine(tmp_path, monkeypatch):
    db_path = tmp_path / "backfill-test.db"
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    yield eng
    eng.dispose()


def test_backfill_membership_creates_one_member_and_membership_per_product(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))

    db_module.Base.metadata.create_all(engine)
    session = db_module.SessionLocal()
    try:
        p1 = products.get_or_create_product(session, org="open-agentos", repo="agentos-pmqs")
        p2 = products.get_or_create_product(session, org="open-agentos", repo="agentos")
    finally:
        session.close()

    db_module._backfill_membership()

    verify = db_module.SessionLocal()
    try:
        assert verify.query(Member).count() == 1
        member = verify.query(Member).first()
        memberships = verify.query(Membership).all()
        assert len(memberships) == 2
        assert {m.product_id for m in memberships} == {p1.id, p2.id}
        assert all(m.member_id == member.id for m in memberships)
        assert all(m.role == "owner" for m in memberships)
    finally:
        verify.close()

    # Idempotent: calling again does not duplicate.
    db_module._backfill_membership()
    verify2 = db_module.SessionLocal()
    try:
        assert verify2.query(Member).count() == 1
        assert verify2.query(Membership).count() == 2
    finally:
        verify2.close()


def test_backfill_membership_noop_when_no_products(engine, monkeypatch):
    import pmqs.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))
    db_module.Base.metadata.create_all(engine)

    db_module._backfill_membership()

    verify = db_module.SessionLocal()
    try:
        assert verify.query(Member).count() == 0
        assert verify.query(Membership).count() == 0
    finally:
        verify.close()
