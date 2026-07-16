from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import products, repository, context_feed


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def pid(db):
    """The product these outcomes land in: create_outcome() with no explicit product_id
    falls back to the account's default product."""
    return products.get_or_create_default_product(db).id


def test_empty_when_no_durable_outcomes(db, pid):
    assert context_feed.build_context_block(db, product_id=pid) == ""


def test_block_includes_active_policy(db, pid):
    repository.create_outcome(db, type="policy", payload={"text": "cap retries at 3"})
    block = context_feed.build_context_block(db, product_id=pid)
    assert "STANDING POLICIES" in block
    assert "cap retries at 3" in block


def test_deactivated_outcome_excluded(db, pid):
    o = repository.create_outcome(db, type="policy", payload={"text": "old rule"})
    repository.deactivate_outcome(db, o.id)
    assert context_feed.build_context_block(db, product_id=pid) == ""


def test_question_and_issue_not_in_feed(db, pid):
    repository.create_outcome(db, type="question", payload={"title": "q"})
    repository.create_outcome(db, type="issue", payload={"title": "i"}, github_ref="http://x")
    assert context_feed.build_context_block(db, product_id=pid) == ""


def test_policies_survive_truncation(db, pid):
    # A long document plus a short policy, with a tiny budget → policy must remain.
    repository.create_outcome(db, type="document", payload={"title": "Big", "body": "x" * 5000})
    repository.create_outcome(db, type="policy", payload={"text": "KEEP THIS POLICY"})
    block = context_feed.build_context_block(db, product_id=pid, char_budget=200)
    assert "KEEP THIS POLICY" in block            # policy first, never dropped
    assert "truncated" in block                     # document body got cut
    assert len(block) <= 240                         # budget + truncation marker


def test_augment_prepends_block(db):
    assert context_feed.augment("PROMPT", "") == "PROMPT"
    out = context_feed.augment("PROMPT", "BLOCK")
    assert out.startswith("BLOCK")
    assert "PROMPT" in out


def test_no_policy_text_ever_bound_to_github(db, pid):
    # Reassert the hard rule at the feed layer: policies are context, never GitHub payload.
    repository.create_outcome(db, type="policy", payload={"text": "secret policy"})
    block = context_feed.build_context_block(db, product_id=pid)
    # The feed is for prompts only; it must not fabricate github refs.
    assert "github" not in block.lower()


# --- Wave 2 item 6 / Loop 1: the policy feed is Product-scoped ---

@pytest.fixture
def two_products(db):
    a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    return a, b


def test_a_colleagues_active_policy_reaches_my_agents(db, two_products):
    """LOOP 1, the whole point of the wave: I never recorded this rule, a colleague did,
    and it still constrains my agents. Product-scoped, not member-scoped (§5)."""
    from pmqs.models import Member

    a, _ = two_products
    colleague = Member(display_name="Ada")
    db.add(colleague)
    db.commit()
    repository.create_outcome(
        db, type="policy", payload={"text": "cap retries at 3"},
        product_id=a.id, author_member_id=colleague.id,
    )

    block = context_feed.build_context_block(db, product_id=a.id)
    assert "cap retries at 3" in block


def test_policies_do_not_cross_the_product_boundary(db, two_products):
    """§2: the boundary is the Product; nothing crosses it. This was a LIVE LEAK before
    Wave 2 item 6 -- build_context_block took no product and returned every product's
    policies to every product's agents."""
    a, b = two_products
    repository.create_outcome(db, type="policy", payload={"text": "PMQS ONLY rule"}, product_id=a.id)
    repository.create_outcome(db, type="policy", payload={"text": "AGENTOS ONLY rule"}, product_id=b.id)

    block_a = context_feed.build_context_block(db, product_id=a.id)
    block_b = context_feed.build_context_block(db, product_id=b.id)

    assert "PMQS ONLY rule" in block_a and "AGENTOS ONLY rule" not in block_a
    assert "AGENTOS ONLY rule" in block_b and "PMQS ONLY rule" not in block_b


def test_retired_policy_does_not_reach_agents(db, two_products):
    """Item 6 acceptance: "retired policies do not". §12's landfill guard -- a shared
    ledger that keeps feeding withdrawn rules gets dumber as the team gets busier."""
    a, _ = two_products
    o = repository.create_outcome(db, type="policy", payload={"text": "withdrawn rule"}, product_id=a.id)
    assert "withdrawn rule" in context_feed.build_context_block(db, product_id=a.id)

    repository.deactivate_outcome(db, o.id)
    assert "withdrawn rule" not in context_feed.build_context_block(db, product_id=a.id)


def test_a_colleagues_retired_policy_does_not_reach_my_agents(db, two_products):
    """Both halves of item 6 at once: shared enough to reach me, retired enough not to."""
    from pmqs.models import Member

    a, _ = two_products
    colleague = Member(display_name="Ada")
    db.add(colleague)
    db.commit()
    o = repository.create_outcome(
        db, type="policy", payload={"text": "superseded rule"},
        product_id=a.id, author_member_id=colleague.id,
    )
    replacement = repository.create_outcome(
        db, type="policy", payload={"text": "current rule"},
        product_id=a.id, author_member_id=colleague.id,
    )
    repository.deactivate_outcome(db, o.id, superseded_by_outcome_id=replacement.id)

    block = context_feed.build_context_block(db, product_id=a.id)
    assert "superseded rule" not in block
    assert "current rule" in block


def test_build_context_block_requires_an_explicit_product(db):
    """The parameter is required on purpose: the leak this item fixed was a function that
    simply never asked which product it was for. Omitting it must fail loudly."""
    with pytest.raises(TypeError):
        context_feed.build_context_block(db)


def test_no_new_feed_mechanism(db, two_products):
    """Item 6: "no new feed mechanism introduced". Policies ride the same unified feed as
    documents and meeting agendas -- one mechanism, wider query."""
    a, _ = two_products
    repository.create_outcome(db, type="policy", payload={"text": "a rule"}, product_id=a.id)
    repository.create_outcome(db, type="document", payload={"title": "D", "body": "a doc"}, product_id=a.id)
    repository.create_outcome(db, type="meeting", payload={"title": "M", "agenda": "an agenda"}, product_id=a.id)

    block = context_feed.build_context_block(db, product_id=a.id)
    assert "STANDING POLICIES" in block
    assert "REFERENCE DOCUMENTS" in block
    assert "MEETING AGENDAS" in block
