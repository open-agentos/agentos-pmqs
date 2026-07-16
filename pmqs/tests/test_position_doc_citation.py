"""Tests for prior-decision citation in the Position Document
(Shared Outcomes build-spec, Wave 2 item 10 — Loop 4).

Acceptance: retrieved prior decisions appear cited with author and date; a prior decision
can appear in the *against* column; no new research pass added.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, position_doc, products, repository
from pmqs.db import Base
from pmqs.models import Member
from pmqs.web.render import _prior_decisions_html


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def me(db):
    return members.get_or_create_default_member(db)


@pytest.fixture
def product(db, me):
    return products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")


@pytest.fixture
def colleague(db, me):
    m = Member(display_name="Ada Lovelace")
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def question(db, product):
    return repository.create_question(db, title="Should we raise enterprise pricing?",
                                      source="system", product_id=product.id)


def _fake_llm(monkeypatch, capture=None):
    monkeypatch.setattr(position_doc.llm, "is_enabled", lambda: True)

    def _complete(system, user, *a, **k):
        if capture is not None:
            capture["system"], capture["user"] = system, user
            capture.setdefault("calls", []).append(1)
        return {k: "text" for k in position_doc.SECTIONS}

    monkeypatch.setattr(position_doc.llm, "complete_json", _complete)


# --- citations carry author and date ---

def test_prior_decisions_are_cited_with_author_and_date(db, product, me, colleague, question,
                                                        monkeypatch):
    o = repository.create_outcome(db, type="policy", payload={"text": "hold pricing flat in 2026"},
                                  product_id=product.id, author_member_id=colleague.id)
    o.created_at = "2026-03-04T10:00:00+00:00"
    db.commit()
    _fake_llm(monkeypatch)

    doc = position_doc.generate(db, question, member_id=me.id)
    cites = doc["prior_decisions"]
    assert len(cites) == 1
    assert cites[0]["author"] == "Ada Lovelace"
    assert cites[0]["date"] == "2026-03-04"
    assert cites[0]["id"] == o.id


def test_author_and_date_reach_the_prompt(db, product, me, colleague, question, monkeypatch):
    """"Who decided this, and when" is what makes a prior decision weighable rather than
    oracular. It has to be in the prompt, not just the payload."""
    o = repository.create_outcome(db, type="policy", payload={"text": "hold pricing flat"},
                                  product_id=product.id, author_member_id=colleague.id)
    o.created_at = "2026-03-04T10:00:00+00:00"
    db.commit()
    cap = {}
    _fake_llm(monkeypatch, cap)

    position_doc.generate(db, question, member_id=me.id)
    assert "Ada Lovelace" in cap["user"]
    assert "2026-03-04" in cap["user"]
    assert "[prior 0]" in cap["user"]


def test_a_doc_with_no_prior_decisions_still_generates(db, product, me, question, monkeypatch):
    _fake_llm(monkeypatch)
    doc = position_doc.generate(db, question, member_id=me.id)
    assert doc["prior_decisions"] == []
    assert doc["degraded"] is False


# --- a prior decision can argue against (§12 groupthink guard) ---

def test_the_prompt_permits_a_prior_decision_in_the_against_column(db, product, me, question,
                                                                   monkeypatch):
    """Item 10 acceptance, and the reason it matters: if prior decisions could only ever
    support the FOR column, the ledger would stop being a memory and become a ratchet --
    every past decision silently reinforcing itself."""
    repository.create_outcome(db, type="policy", payload={"text": "hold pricing flat"},
                              product_id=product.id, author_member_id=me.id)
    cap = {}
    _fake_llm(monkeypatch, cap)

    position_doc.generate(db, question, member_id=me.id)
    assert "argument_against" in cap["system"]
    assert "NOT A VERDICT" in cap["system"]
    assert "Never treat a prior decision as settling the question" in cap["system"]
    assert "evidence, not verdicts" in cap["user"]


# --- no new research pass ---

def test_exactly_one_llm_call_is_made(db, product, me, colleague, question, monkeypatch):
    """"No new research pass added" (item 10 acceptance). The whole point of a
    Product-wide ledger is that the prior thinking is already there -- paying an LLM to
    rediscover it would be the joke."""
    for i in range(5):
        repository.create_outcome(db, type="document",
                                  payload={"title": f"brief {i}", "body": "b"},
                                  product_id=product.id, author_member_id=colleague.id)
    cap = {}
    _fake_llm(monkeypatch, cap)

    position_doc.generate(db, question, member_id=me.id)
    assert len(cap["calls"]) == 1


# --- visibility and resilience ---

def test_a_doc_never_cites_another_members_private_room(db, product, me, colleague, question,
                                                        monkeypatch):
    """A doc must not become a side channel around §4."""
    room = repository.open_session(db, topic="secret", product_id=product.id,
                                   author_member_id=colleague.id, visibility="private")
    repository.create_outcome(db, type="policy", payload={"text": "SECRET RULE"},
                              session_id=room.id, product_id=product.id,
                              author_member_id=colleague.id)
    cap = {}
    _fake_llm(monkeypatch, cap)

    doc = position_doc.generate(db, question, member_id=me.id)
    assert doc["prior_decisions"] == []
    assert "SECRET RULE" not in cap["user"]


def test_retired_decisions_are_not_cited(db, product, me, question, monkeypatch):
    o = repository.create_outcome(db, type="policy", payload={"text": "withdrawn rule"},
                                  product_id=product.id, author_member_id=me.id)
    repository.deactivate_outcome(db, o.id)
    _fake_llm(monkeypatch)

    assert position_doc.generate(db, question, member_id=me.id)["prior_decisions"] == []


def test_citations_do_not_cross_the_product_boundary(db, me, colleague, monkeypatch):
    a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    repository.create_outcome(db, type="policy", payload={"text": "other product rule"},
                              product_id=b.id, author_member_id=colleague.id)
    q = repository.create_question(db, title="q", source="system", product_id=a.id)
    _fake_llm(monkeypatch)

    assert position_doc.generate(db, q, member_id=me.id)["prior_decisions"] == []


def test_citation_lookup_failure_does_not_break_the_doc(db, product, me, question, monkeypatch):
    """A doc without citations is worse; a doc that 500s is useless."""
    from pmqs import retrieval

    monkeypatch.setattr(retrieval, "select_prior_outcomes",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _fake_llm(monkeypatch)

    doc = position_doc.generate(db, question, member_id=me.id)
    assert doc["prior_decisions"] == []
    assert doc["degraded"] is False


def test_fallback_doc_is_unchanged_when_llm_is_off(db, product, me, question):
    doc = position_doc.generate(db, question, member_id=me.id)
    assert doc["degraded"] is True


# --- rendering ---

def test_rendered_doc_shows_the_citation_with_author_and_date():
    """An inline [prior 0] with nothing to resolve it against is not a citation."""
    out = _prior_decisions_html([
        {"ref": 0, "id": "x", "type": "policy", "author": "Ada Lovelace",
         "date": "2026-03-04", "text": "hold pricing flat"}
    ])
    assert "[prior 0]" in out
    assert "Ada Lovelace" in out
    assert "2026-03-04" in out


def test_rendered_citations_are_escaped():
    out = _prior_decisions_html([
        {"ref": 0, "id": "x", "type": "policy", "author": "<script>alert(1)</script>",
         "date": "2026-03-04", "text": "<img src=x onerror=1>"}
    ])
    assert "<script>alert(1)</script>" not in out
    assert "<img src=x" not in out


def test_no_citations_renders_nothing():
    assert _prior_decisions_html([]) == ""
