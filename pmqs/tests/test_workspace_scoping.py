"""Tests for workspace_id scoping across hosted-store tables + backfill (issue #52)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products, repository
from pmqs.db import Base
from pmqs.models import NewsItem, Outcome, Question
from pmqs.models import Session as SessionModel


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


def test_create_question_without_workspace_id_falls_back_to_default(db):
    q = repository.create_question(db, title="Ship or wait?", source="system")
    assert q.workspace_id is not None
    ws = products.get_or_create_default_workspace(db)
    assert q.workspace_id == ws.id


def test_list_questions_scoped_to_workspace(db):
    product_a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    product_b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    ws_a = products.create_workspace(db, product=product_a)
    ws_b = products.create_workspace(db, product=product_b)

    repository.create_question(db, title="A question", source="system", workspace_id=ws_a.id)
    repository.create_question(db, title="B question", source="system", workspace_id=ws_b.id)

    only_a = repository.list_questions(db, workspace_id=ws_a.id)
    only_b = repository.list_questions(db, workspace_id=ws_b.id)
    assert [q.title for q in only_a] == ["A question"]
    assert [q.title for q in only_b] == ["B question"]

    # Omitting workspace_id still returns everything -- back-compat for pre-#56 callers.
    assert len(repository.list_questions(db, workspace_id=None)) == 2


def test_outcomes_and_sessions_scoped_to_workspace(db):
    product_a = products.get_or_create_product(db, org="acme", repo="widgets")
    product_b = products.get_or_create_product(db, org="acme", repo="gizmos")
    ws_a = products.create_workspace(db, product=product_a)
    ws_b = products.create_workspace(db, product=product_b)

    repository.create_outcome(db, type="document", payload={"title": "A doc"}, workspace_id=ws_a.id)
    repository.create_outcome(db, type="document", payload={"title": "B doc"}, workspace_id=ws_b.id)
    repository.open_session(db, topic="A session", workspace_id=ws_a.id)
    repository.open_session(db, topic="B session", workspace_id=ws_b.id)

    assert len(repository.list_outcomes(db, workspace_id=ws_a.id)) == 1
    assert len(repository.list_outcomes(db, workspace_id=ws_b.id)) == 1
    assert len(repository.list_durable_outcomes(db, workspace_id=ws_a.id)) == 1

    sessions_a = db.scalars(select(SessionModel).where(SessionModel.workspace_id == ws_a.id)).all()
    assert len(sessions_a) == 1
    assert sessions_a[0].topic == "A session"


def test_backfill_assigns_default_workspace_to_pre_existing_rows(db):
    # Simulate rows created before the Product/Workspace model existed: insert directly
    # via the ORM with no workspace_id at all (bypassing the repository fallback).
    db.add(Question(title="legacy question", source="system"))
    db.add(Outcome(type="document", payload="{}"))
    db.add(SessionModel(topic="legacy session"))
    db.add(NewsItem(url="https://example.com/legacy", title="legacy news"))
    db.commit()

    assert db.query(Question).filter(Question.workspace_id.is_(None)).count() == 1

    # _backfill_default_workspace() opens its own SessionLocal() bound to the real
    # module-level engine, not this test's isolated in-memory one -- so instead we
    # exercise the same logic path it uses, against this test's session, directly.
    from sqlalchemy import update

    ws = products.get_or_create_default_workspace(db)
    for model in (Question, Outcome, SessionModel, NewsItem):
        db.execute(update(model).where(model.workspace_id.is_(None)).values(workspace_id=ws.id))
    db.commit()

    assert db.query(Question).filter(Question.workspace_id.is_(None)).count() == 0
    assert db.get(Question, db.scalars(select(Question.id)).first()).workspace_id == ws.id


def test_backfill_default_workspace_integration(monkeypatch):
    """Exercise the real db._backfill_default_workspace() (not just its logic inline),
    by pointing the module's engine/SessionLocal at a throwaway in-memory DB."""
    from pmqs import db as db_module

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)

    seed = TestSessionLocal()
    seed.add(Question(title="legacy question", source="system"))
    seed.commit()
    seed.close()

    db_module._backfill_default_workspace()

    check = TestSessionLocal()
    q = check.scalars(select(Question)).first()
    assert q.workspace_id is not None
    check.close()
