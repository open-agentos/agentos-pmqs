"""Tests for Member/Membership (Shared Outcomes build-spec, Wave 1 item 1)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products
from pmqs.db import Base
from pmqs.models import Membership


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    yield session
    session.close()


def test_get_or_create_default_member_is_singleton(db):
    m1 = members.get_or_create_default_member(db)
    m2 = members.get_or_create_default_member(db)
    assert m1.id == m2.id


def test_ensure_membership_creates_owner_role(db):
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    member = members.get_or_create_default_member(db)
    membership = members.ensure_membership(db, member=member, product=product, role="owner")
    assert membership.role == "owner"
    assert membership.member_id == member.id
    assert membership.product_id == product.id


def test_ensure_membership_idempotent(db):
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    member = members.get_or_create_default_member(db)
    m1 = members.ensure_membership(db, member=member, product=product, role="owner")
    m2 = members.ensure_membership(db, member=member, product=product, role="owner")
    assert m1.member_id == m2.member_id
    assert m1.product_id == m2.product_id
    assert db.query(Membership).count() == 1


def test_list_memberships_scoped_to_member(db):
    p1 = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    p2 = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    member = members.get_or_create_default_member(db)
    members.ensure_membership(db, member=member, product=p1, role="owner")
    members.ensure_membership(db, member=member, product=p2, role="owner")
    rows = members.list_memberships(db, member_id=member.id)
    assert {r.product_id for r in rows} == {p1.id, p2.id}
