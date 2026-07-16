"""Tests for the initial seed lens pass on new Workspace creation (issue #54)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import pipeline, products, repository
from pmqs.agentos_client import AgentOSClientError
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


_STATE_WITH_STALE_ISSUE = {
    "issues": [
        {
            "number": 1,
            "title": "Old open issue",
            "body": "",
            "url": "https://github.com/acme/widgets/issues/1",
            "labels": [],
            "createdAt": "2000-01-01T00:00:00Z",
            "updatedAt": "2000-01-01T00:00:00Z",
            "author": {"login": "someone"},
            "state": "OPEN",
        }
    ],
    "labels": [],
}


def test_seed_workspace_persists_questions_scoped_to_workspace(db, monkeypatch):
    product = products.get_or_create_product(db, org="acme", repo="widgets")
    workspace = products.create_workspace(db, product=product)

    monkeypatch.setattr(
        "pmqs.agentos_client.AgentOSClient.get_state",
        lambda self: _STATE_WITH_STALE_ISSUE,
    )

    questions = pipeline.seed_workspace(db, workspace)

    assert len(questions) >= 1
    assert all(q.workspace_id == workspace.id for q in questions)
    # Doesn't leak into a different workspace's inbox.
    other_product = products.get_or_create_product(db, org="acme", repo="gizmos")
    other_workspace = products.create_workspace(db, product=other_product)
    assert repository.list_questions(db, workspace_id=other_workspace.id) == []


def test_seed_workspace_uses_the_products_own_repo(db, monkeypatch):
    product = products.get_or_create_product(db, org="acme", repo="widgets")
    workspace = products.create_workspace(db, product=product)

    seen_repos = []

    def fake_get_state(self):
        seen_repos.append(self.repo)
        return {"issues": [], "labels": []}

    monkeypatch.setattr("pmqs.agentos_client.AgentOSClient.get_state", fake_get_state)
    pipeline.seed_workspace(db, workspace)

    assert seen_repos == ["acme/widgets"]


def test_seed_workspace_returns_empty_on_fetch_failure(db, monkeypatch):
    product = products.get_or_create_product(db, org="acme", repo="widgets")
    workspace = products.create_workspace(db, product=product)

    def raise_error(self):
        raise AgentOSClientError("boom")

    monkeypatch.setattr("pmqs.agentos_client.AgentOSClient.get_state", raise_error)

    assert pipeline.seed_workspace(db, workspace) == []
