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


def test_add_product_creates_product(client):
    r = client.post("/products", data={"repo": "open-agentos/agentos"}, follow_redirects=False)
    assert r.status_code == 303

    db = client._session_factory()
    all_products = products.list_products(db)
    repos = {p.full_name for p in all_products}
    assert "open-agentos/agentos" in repos
    db.close()


def test_add_product_rejects_malformed_repo_ref(client):
    r = client.post("/products", data={"repo": "not-a-valid-ref"}, follow_redirects=False)
    assert r.status_code == 303
    assert "product_error" in r.headers["location"]


def test_add_product_twice_resolves_to_the_same_product(client):
    client.post("/products", data={"repo": "open-agentos/agentos", "nickname": "First"})
    client.post("/products", data={"repo": "open-agentos/agentos", "nickname": "Second"})

    db = client._session_factory()
    matching = [p for p in products.list_products(db) if p.full_name == "open-agentos/agentos"]
    # Adding the same repo twice resolves to ONE Product row (Membership, not a
    # second Product row, is how sharing across PMs works -- see models.Product).
    assert len(matching) == 1
    db.close()


def test_api_workspaces_lists_added_products(client):
    client.post("/products", data={"repo": "open-agentos/agentos-pmqs"})
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert any(w["product_repo"] == "open-agentos/agentos-pmqs" for w in body)
