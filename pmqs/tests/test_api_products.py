"""API-level tests for the Add Product flow (issue #53)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products
from pmqs.api.app import app
from pmqs.db import Base, get_session


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        c._session_factory = TestingSession
        yield c
    app.dependency_overrides.clear()


def test_add_product_creates_product_and_workspace(client):
    r = client.post("/products", data={"repo": "open-agentos/agentos"}, follow_redirects=False)
    assert r.status_code == 303

    db = client._session_factory()
    workspaces = products.list_workspaces(db)
    repos = {products.get_product(db, ws.product_id).full_name for ws in workspaces}
    assert "open-agentos/agentos" in repos
    db.close()


def test_add_product_rejects_malformed_repo_ref(client):
    r = client.post("/products", data={"repo": "not-a-valid-ref"}, follow_redirects=False)
    assert r.status_code == 303
    assert "product_error" in r.headers["location"]


def test_add_product_twice_shares_product_but_makes_two_workspaces(client):
    client.post("/products", data={"repo": "open-agentos/agentos", "nickname": "First"})
    client.post("/products", data={"repo": "open-agentos/agentos", "nickname": "Second"})

    db = client._session_factory()
    workspaces = [ws for ws in products.list_workspaces(db) if ws.nickname in ("First", "Second")]
    assert len(workspaces) == 2
    assert workspaces[0].product_id == workspaces[1].product_id  # shared Product row
    assert workspaces[0].id != workspaces[1].id  # separate Workspaces
    db.close()


def test_api_workspaces_lists_added_products(client):
    client.post("/products", data={"repo": "open-agentos/agentos-pmqs"})
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert any(w["product_repo"] == "open-agentos/agentos-pmqs" for w in body)
