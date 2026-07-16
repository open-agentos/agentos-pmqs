"""Tests for the Product/Workspace multi-product model (issue #51)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products
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


def test_two_workspaces_can_share_one_product(db):
    # Two "different PMs" (simulated via distinct account_id) adding the same repo
    # share the Product row but get separate Workspaces.
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    ws_a = products.create_workspace(db, product=product, account_id="pm-a")
    ws_b = products.create_workspace(db, product=product, account_id="pm-b")

    assert ws_a.product_id == ws_b.product_id == product.id
    assert ws_a.id != ws_b.id
    assert ws_a.slug != ws_b.slug  # disambiguated even though both derive from "agentos"


def test_list_workspaces_scoped_to_account(db):
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    products.create_workspace(db, product=product, account_id="pm-a")
    products.create_workspace(db, product=product, account_id="pm-b")

    assert len(products.list_workspaces(db, account_id="pm-a")) == 1
    assert len(products.list_workspaces(db, account_id="pm-b")) == 1


def test_get_or_create_default_workspace_seeds_from_config(db):
    ws = products.get_or_create_default_workspace(db)
    product = products.get_product(db, ws.product_id)
    assert product is not None
    assert product.full_name  # non-empty org/repo derived from config.AGENTOS_REPO

    # Idempotent: calling again returns the same workspace rather than creating another.
    ws2 = products.get_or_create_default_workspace(db)
    assert ws.id == ws2.id


def test_workspace_display_name_prefers_nickname(db):
    product = products.get_or_create_product(db, org="open-agentos", repo="agentos", display_name="AgentOS")
    ws = products.create_workspace(db, product=product, nickname="My Core Product")
    assert products.workspace_display_name(db, ws) == "My Core Product"

    ws2 = products.create_workspace(db, product=product)
    assert products.workspace_display_name(db, ws2) == "AgentOS"
