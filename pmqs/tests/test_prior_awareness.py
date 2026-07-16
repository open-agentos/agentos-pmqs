"""Tests for prior-outcome awareness in question generation + dedup
(Shared Outcomes build-spec §10.3, Wave 2 item 9 — Loops 2 and 3).

The test that earns its keep here is test_a_challenge_to_a_prior_decision_is_raised:
§10.3 and §12 both insist prior decisions are positions to test, not settled fact, and a
challenge to a policy has near-total word overlap with it. Any dedup that "works" on
similarity alone destroys exactly the question worth asking.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import dedup as dedup_mod, members, products, repository
from pmqs.db import Base
from pmqs.dedup import judge_prior_awareness, raisable
from pmqs.models import Member


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
def colleague(db, me):
    m = Member(display_name="Ada")
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def product(db, me):
    return products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")


def _cand(title, description=""):
    return {"title": title, "description": description, "lens_tags": [], "evidence": [],
            "source": "system"}


def _fake_llm(monkeypatch, response):
    monkeypatch.setattr(dedup_mod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(dedup_mod.llm, "complete_json", lambda *a, **k: response)


def _judge(db, product, me, cands, **kw):
    return judge_prior_awareness(cands, db, product_id=product.id, member_id=me.id, **kw)


# --- the groupthink guard (§10.3, §12) ---

def test_a_challenge_to_a_prior_decision_is_raised(db, product, me, monkeypatch):
    """THE test for this item. A question arguing against a standing policy shares almost
    every word with it. It must survive -- "prior decisions are positions to test, not
    settled fact"."""
    repository.create_outcome(db, type="policy", payload={"text": "never ship on a Friday"},
                              product_id=product.id, author_member_id=me.id)
    _fake_llm(monkeypatch, {"verdict": "raise", "prior_ref": 0, "reason": "challenges it"})

    cands = _judge(db, product, me, [_cand("Should we revisit never shipping on a Friday?")])
    assert cands[0]["_verdict"] == "raise"
    assert len(raisable(cands)) == 1


def test_the_prompt_tells_the_model_prior_decisions_are_not_settled(db, product, me, monkeypatch):
    """The guard has to be in the instruction, not just in our hopes."""
    seen = {}

    def _capture(system, user, *a, **k):
        seen["system"], seen["user"] = system, user
        return {"verdict": "raise"}

    repository.create_outcome(db, type="policy", payload={"text": "a rule"},
                              product_id=product.id, author_member_id=me.id)
    monkeypatch.setattr(dedup_mod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(dedup_mod.llm, "complete_json", _capture)

    _judge(db, product, me, [_cand("q")])
    assert "POSITIONS TO TEST" in seen["system"]
    assert "NOT SETTLED FACT" in seen["system"]
    assert "positions to test, not settled fact" in seen["user"]


# --- fail open ---

def test_without_an_llm_nothing_is_suppressed(db, product, me):
    """Rule 2: the fallback never suppresses. Raising a duplicate is visible and costs a
    minute; suppressing a novel question is invisible and unrecoverable."""
    repository.create_outcome(db, type="policy", payload={"text": "never ship on a Friday"},
                              product_id=product.id, author_member_id=me.id)

    cands = _judge(db, product, me, [_cand("never ship on a Friday")])  # a literal duplicate
    assert cands[0]["_verdict"] == "raise"


def test_llm_failure_degrades_to_raise(db, product, me, monkeypatch):
    repository.create_outcome(db, type="policy", payload={"text": "a rule"},
                              product_id=product.id, author_member_id=me.id)
    monkeypatch.setattr(dedup_mod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(dedup_mod.llm, "complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    assert _judge(db, product, me, [_cand("q")])[0]["_verdict"] == "raise"


def test_a_nonsense_verdict_degrades_to_raise(db, product, me, monkeypatch):
    repository.create_outcome(db, type="policy", payload={"text": "a rule"},
                              product_id=product.id, author_member_id=me.id)
    _fake_llm(monkeypatch, {"verdict": "delete_everything"})

    assert _judge(db, product, me, [_cand("q")])[0]["_verdict"] == "raise"


def test_suppress_with_no_prior_named_degrades_to_raise(db, product, me, monkeypatch):
    """A suppress that points at nothing is the model saying "duplicate" with no
    duplicate to show. Don't act on it."""
    repository.create_outcome(db, type="policy", payload={"text": "a rule"},
                              product_id=product.id, author_member_id=me.id)
    _fake_llm(monkeypatch, {"verdict": "suppress", "prior_ref": None})

    assert _judge(db, product, me, [_cand("q")])[0]["_verdict"] == "raise"


def test_evidence_assembly_failure_raises_everything(db, product, me, monkeypatch):
    monkeypatch.setattr(dedup_mod, "_prior_evidence",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    cands = _judge(db, product, me, [_cand("a"), _cand("b")])
    assert [c["_verdict"] for c in cands] == ["raise", "raise"]


# --- verdicts ---

def test_suppress_drops_the_candidate(db, product, me, monkeypatch):
    o = repository.create_outcome(db, type="policy", payload={"text": "cap retries at 3"},
                                  product_id=product.id, author_member_id=me.id)
    _fake_llm(monkeypatch, {"verdict": "suppress", "prior_ref": 0})

    cands = _judge(db, product, me, [_cand("Should we cap retries at 3?")])
    assert cands[0]["_verdict"] == "suppress"
    assert cands[0]["_prior_outcome_id"] == o.id
    assert raisable(cands) == []


def test_reframe_raises_and_annotates(db, product, me, monkeypatch):
    o = repository.create_outcome(db, type="document", payload={"title": "Pricing", "body": "b"},
                                  product_id=product.id, author_member_id=me.id)
    _fake_llm(monkeypatch, {"verdict": "reframe", "prior_ref": 0})

    cands = _judge(db, product, me, [_cand("Tier-3 pricing?")])
    assert cands[0]["_verdict"] == "reframe"
    assert cands[0]["_prior_outcome_id"] == o.id
    assert len(raisable(cands)) == 1
    assert "Builds on an earlier decision" in cands[0]["description"]
    # even when reframing, the prior decision stays contestable
    assert "position to test" in cands[0]["description"]


def test_route_points_at_a_colleagues_visible_workspace(db, product, me, colleague, monkeypatch):
    q = repository.create_question(db, title="Are we losing on price?", source="system",
                                   product_id=product.id, author_member_id=colleague.id)
    room = repository.open_session(db, topic="Are we losing on price?", question_id=q.id,
                                   product_id=product.id, author_member_id=colleague.id,
                                   visibility="shared")
    _fake_llm(monkeypatch, {"verdict": "route", "colleague_ref": 0})

    cands = _judge(db, product, me, [_cand("Are we losing on price?")])
    assert cands[0]["_verdict"] == "route"
    assert cands[0]["_route_session_id"] == room.id
    assert raisable(cands) == []  # surfaced, not raised twice


def test_route_to_a_private_room_degrades_to_raise(db, product, me, colleague, monkeypatch):
    """Routing into a colleague's private room would leak its existence AND its topic
    (§4). Better a duplicate question than a privacy hole."""
    q = repository.create_question(db, title="secret work", source="system",
                                   product_id=product.id, author_member_id=colleague.id)
    repository.open_session(db, topic="secret work", question_id=q.id, product_id=product.id,
                            author_member_id=colleague.id, visibility="private")
    _fake_llm(monkeypatch, {"verdict": "route", "colleague_ref": 0})

    cands = _judge(db, product, me, [_cand("secret work")])
    assert cands[0]["_verdict"] == "raise"
    assert "_route_session_id" not in cands[0]
    assert len(raisable(cands)) == 1


def test_route_with_no_room_open_degrades_to_raise(db, product, me, colleague, monkeypatch):
    """The colleague has it in their inbox but hasn't opened a room -- there is no
    Workspace to surface, so routing has nowhere to point."""
    repository.create_question(db, title="not started", source="system",
                               product_id=product.id, author_member_id=colleague.id)
    _fake_llm(monkeypatch, {"verdict": "route", "colleague_ref": 0})

    assert _judge(db, product, me, [_cand("not started")])[0]["_verdict"] == "raise"


# --- evidence boundaries ---

def test_my_own_inbox_items_are_not_colleague_evidence(db, product, me):
    repository.create_question(db, title="mine", source="system",
                               product_id=product.id, author_member_id=me.id)
    assert repository.list_other_members_open_questions(
        db, product_id=product.id, member_id=me.id) == []


def test_colleague_evidence_does_not_cross_the_product(db, me, colleague):
    a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    repository.create_question(db, title="theirs elsewhere", source="system",
                               product_id=b.id, author_member_id=colleague.id)

    assert repository.list_other_members_open_questions(
        db, product_id=a.id, member_id=me.id) == []


def test_closed_inbox_items_are_not_colleague_evidence(db, product, me, colleague):
    """Only OPEN items (§10.3) -- a dismissed or promoted question is no longer something
    a colleague is deciding."""
    q = repository.create_question(db, title="done", source="system",
                                   product_id=product.id, author_member_id=colleague.id)
    repository.update_question_status(db, q.id, "dismissed")

    assert repository.list_other_members_open_questions(
        db, product_id=product.id, member_id=me.id) == []


def test_no_second_llm_judgment_is_added(db, product, me, monkeypatch):
    """§10.3: "Widen the existing LLM dedup judgment -- do not add a second one." One
    candidate, one prior-awareness call."""
    calls = []
    repository.create_outcome(db, type="policy", payload={"text": "a rule"},
                              product_id=product.id, author_member_id=me.id)
    monkeypatch.setattr(dedup_mod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(dedup_mod.llm, "complete_json",
                        lambda *a, **k: calls.append(1) or {"verdict": "raise"})

    _judge(db, product, me, [_cand("q")])
    assert len(calls) == 1


def test_no_evidence_means_no_llm_call_at_all(db, product, me, monkeypatch):
    """Empty product: nothing to judge against, so don't spend a call to be told so."""
    calls = []
    monkeypatch.setattr(dedup_mod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(dedup_mod.llm, "complete_json",
                        lambda *a, **k: calls.append(1) or {"verdict": "raise"})

    cands = _judge(db, product, me, [_cand("q")])
    assert calls == []
    assert cands[0]["_verdict"] == "raise"
