"""Tests for the Product model (issue #51, folded per Shared Outcomes build-spec
§8 step 2 -- workspace's slug/nickname/lens_weights/archived now live on Product
directly; Membership is the peer-sharing mechanism, not a second per-tenant row).
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products
from pmqs.db import Base


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


def test_parse_repo_ref():
    assert products.parse_repo_ref("open-agentos/agentos") == ("open-agentos", "agentos")
    assert products.parse_repo_ref("/open-agentos/agentos/") == ("open-agentos", "agentos")
    with pytest.raises(ValueError):
        products.parse_repo_ref("not-a-repo-ref")


def test_get_or_create_product_dedupes_by_org_repo(db):
    p1 = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    p2 = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    assert p1.id == p2.id
    assert p1.full_name == "open-agentos/agentos"


def test_two_members_can_share_one_product_via_membership(db):
    # Two PMs adding the same repo resolve to ONE Product row; sharing across them is
    # via Membership rows (not via separate Product rows per-PM, the pre-fold model).
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    member_a = members.get_or_create_default_member(db)
    membership_a = members.ensure_membership(db, member=member_a, product=product, role="owner")

    assert membership_a.product_id == product.id
    # A second membership on the same product (simulating a peer joining) shares the
    # Product row, not a second copy of it.
    from pmqs.models import Member

    member_b = Member(display_name="Peer PM")
    db.add(member_b)
    db.commit()
    membership_b = members.ensure_membership(db, member=member_b, product=product, role="member")
    assert membership_b.product_id == membership_a.product_id
    assert membership_a.member_id != membership_b.member_id


def test_list_products_returns_created_products(db):
    products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    products.get_or_create_product(db, org="open-agentos", repo="agentos")

    assert len(products.list_products(db)) == 2


def test_get_or_create_default_product_seeds_from_config(db):
    p = products.get_or_create_default_product(db)
    assert p is not None
    assert p.full_name  # non-empty org/repo derived from config.AGENTOS_REPO

    # Idempotent: calling again returns the same product rather than creating another.
    p2 = products.get_or_create_default_product(db)
    assert p.id == p2.id


def test_product_display_name_prefers_nickname(db):
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos", display_name="AgentOS")
    assert products.product_display_name(db, product) == "AgentOS"

    product2 = products.get_or_create_product(
        db, org="open-agentos", repo="agentos-pmqs", nickname="My Core Product"
    )
    assert products.product_display_name(db, product2) == "My Core Product"


def test_new_product_gets_a_unique_slug(db):
    p1 = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    p2 = products.get_or_create_product(db, org="acme", repo="agentos")  # same basename
    assert p1.slug != p2.slug
