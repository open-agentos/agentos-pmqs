from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import products, repository, settings
import pmqs.news.relevance as relevance


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def _seed(db, n=3, product=None):
    """News items belong to a Product as of #96 -- promote_relevant loops products, so
    an item with no product_id is now invisible to it (which is the point)."""
    product = product or products.get_or_create_default_product(db)
    # URLs namespaced per product: `news_items.url` is globally unique, not
    # (product_id, url), so a shared URL would collide across products. See the
    # accepted-dupe test at the bottom of this file.
    for i in range(n):
        repository.create_news_item(db, url=f"http://x/{product.repo}/{i}", title=f"News {i}",
                                    source_label="pub.example", summary="s",
                                    published_at="2026-07-14", product_id=product.id)
    return product


def _profile(db, text, product=None):
    products.set_news_config(db, product or products.get_or_create_default_product(db),
                             product_profile=text)


def test_promote_empty_when_llm_off(db, monkeypatch):
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: False)
    _seed(db)
    assert relevance.promote_relevant(db) == []


def test_relevant_items_become_news_questions(db, monkeypatch):
    _seed(db, 3)
    settings.set_news_config(db, top_n=3, min_relevance=0.5)
    _profile(db, "PMQs")
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    # LLM says item 0 highly relevant, item 1 below threshold, item 2 relevant.
    def fake(system, user, **kw):
        return {"items": [
            {"index": 0, "relevance": 0.9, "title": "Provocative Q about #0", "description": "reportedly big"},
            {"index": 1, "relevance": 0.2, "title": "weak", "description": "meh"},
            {"index": 2, "relevance": 0.7, "title": "Q about #2", "description": "according to pub"},
        ]}
    monkeypatch.setattr(relevance.llm, "complete_json", fake)

    qs = relevance.promote_relevant(db)
    assert len(qs) == 2  # index 1 dropped (below threshold)
    for q in qs:
        assert q.source == "news"
        assert q.status == "proposed"
        assert q.score is not None
        ev = q.evidence_list[0]
        assert ev["type"] == "news"
        assert ev["hedged"] is True
        assert ev["url"].startswith("http")
    # all raw items marked processed
    assert repository.list_news_items(db, unprocessed_only=True) == []


def test_top_n_cap(db, monkeypatch):
    _seed(db, 5)
    settings.set_news_config(db, top_n=2, min_relevance=0.3)
    _profile(db, "P")
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    def fake(system, user, **kw):
        return {"items": [
            {"index": i, "relevance": 0.9 - i * 0.05, "title": f"T{i}", "description": "d"}
            for i in range(5)
        ]}
    monkeypatch.setattr(relevance.llm, "complete_json", fake)
    qs = relevance.promote_relevant(db)
    assert len(qs) == 2  # capped at top_n


def test_nothing_relevant_marks_processed_and_returns_empty(db, monkeypatch):
    _seed(db, 2)
    settings.set_news_config(db, top_n=3, min_relevance=0.8)
    _profile(db, "P")
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(relevance.llm, "complete_json",
                        lambda s, u, **k: {"items": [{"index": 0, "relevance": 0.1, "title": "x", "description": "y"}]})
    assert relevance.promote_relevant(db) == []
    # batch still marked processed so it isn't re-judged
    assert repository.list_news_items(db, unprocessed_only=True) == []


def test_survives_llm_exception(db, monkeypatch):
    _seed(db, 2)
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(relevance.llm, "complete_json", boom)
    assert relevance.promote_relevant(db) == []  # no crash
    # on failure we do NOT mark processed (so a retry can judge them)
    assert len(repository.list_news_items(db, unprocessed_only=True)) == 2


def test_news_question_never_carries_github_ref(db, monkeypatch):
    _seed(db, 1)
    settings.set_news_config(db, top_n=3, min_relevance=0.1)
    _profile(db, "P")
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(relevance.llm, "complete_json",
                        lambda s, u, **k: {"items": [{"index": 0, "relevance": 0.9, "title": "T", "description": "d"}]})
    qs = relevance.promote_relevant(db)
    # news evidence must be a citation, never a github ref
    ev = qs[0].evidence_list[0]
    assert "github" not in str(ev).lower()


def test_news_uses_llm_picked_lens(db, monkeypatch):
    # B5: the LLM's per-item lens is used when valid.
    _seed(db, 1)
    settings.set_news_config(db, top_n=3, min_relevance=0.1)
    _profile(db, "P")
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(relevance.llm, "complete_json", lambda s, u, **k: {"items": [
        {"index": 0, "relevance": 0.9, "lens": "unit_economics", "title": "T", "description": "d"},
    ]})
    qs = relevance.promote_relevant(db)
    assert qs[0].lens_tags_list == ["unit_economics"]


def test_news_invalid_lens_falls_back(db, monkeypatch):
    _seed(db, 1)
    settings.set_news_config(db, top_n=3, min_relevance=0.1)
    _profile(db, "P")
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(relevance.llm, "complete_json", lambda s, u, **k: {"items": [
        {"index": 0, "relevance": 0.9, "lens": "not_a_real_lens", "title": "T", "description": "d"},
    ]})
    qs = relevance.promote_relevant(db)
    assert qs[0].lens_tags_list == ["competitive_positioning"]  # default fallback


# --- #96: the relevance pass is per Product ---


def _fake_llm(monkeypatch, title="Q"):
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    seen = []

    def fake(system, user, **kw):
        seen.append(user)
        return {"items": [{"index": 0, "relevance": 0.9, "title": title, "description": "d"}]}

    monkeypatch.setattr(relevance.llm, "complete_json", fake)
    return seen


def test_questions_carry_the_product_of_their_news_item(db, monkeypatch):
    """Before #96, news Questions were created with product_id=None and could surface
    in any product's inbox."""
    a = products.get_or_create_product(db, org="o", repo="a")
    _seed(db, 1, product=a)
    _profile(db, "A profile", product=a)
    settings.set_news_config(db, top_n=3, min_relevance=0.5)
    _fake_llm(monkeypatch)

    qs = relevance.promote_relevant(db)
    assert len(qs) == 1
    assert qs[0].product_id == a.id


def test_each_product_is_judged_against_its_own_profile(db, monkeypatch):
    a = products.get_or_create_product(db, org="o", repo="a")
    b = products.get_or_create_product(db, org="o", repo="b")
    repository.create_news_item(db, url="http://x/a", title="A news", product_id=a.id)
    repository.create_news_item(db, url="http://x/b", title="B news", product_id=b.id)
    _profile(db, "profile for A", product=a)
    _profile(db, "profile for B", product=b)
    settings.set_news_config(db, top_n=3, min_relevance=0.5)
    prompts = _fake_llm(monkeypatch)

    qs = relevance.promote_relevant(db)
    assert len(qs) == 2
    assert {q.product_id for q in qs} == {a.id, b.id}
    # Two passes, each seeing only its own product's profile and items.
    assert len(prompts) == 2
    a_prompt = next(p for p in prompts if "profile for A" in p)
    assert "A news" in a_prompt and "B news" not in a_prompt
    assert "profile for B" not in a_prompt


def test_a_product_with_no_items_is_skipped_not_crashed(db, monkeypatch):
    a = products.get_or_create_product(db, org="o", repo="a")
    products.get_or_create_product(db, org="o", repo="empty")
    _seed(db, 1, product=a)
    _profile(db, "A", product=a)
    prompts = _fake_llm(monkeypatch)
    assert len(relevance.promote_relevant(db)) == 1
    assert len(prompts) == 1


def test_missing_profile_degrades_rather_than_crashing(db, monkeypatch):
    a = products.get_or_create_product(db, org="o", repo="a")
    _seed(db, 1, product=a)
    prompts = _fake_llm(monkeypatch)
    assert len(relevance.promote_relevant(db)) == 1
    assert "(no product profile configured)" in prompts[0]


def test_top_n_is_per_product(db, monkeypatch):
    """Two products, top_n=1 => one question each, not one overall."""
    for name in ("a", "b"):
        p = products.get_or_create_product(db, org="o", repo=name)
        _seed(db, 2, product=p)
        _profile(db, name, product=p)
    settings.set_news_config(db, top_n=1, min_relevance=0.5)
    _fake_llm(monkeypatch)
    assert len(relevance.promote_relevant(db)) == 2


def test_same_story_across_two_products_is_lost_to_the_second(db, monkeypatch):
    """ACCEPTED at MVP (#96), pinned so it's a decision and not a surprise.

    `news_items.url` is globally unique rather than (product_id, url), so when two
    products watch the same story the second product never sees it. The fix is a full
    SQLite table rebuild (can't ALTER a UNIQUE in place), judged not worth paying for at
    one user with two products. If this test starts mattering -- peers, or many products
    per account -- that's the signal to pay for it.
    """
    a = products.get_or_create_product(db, org="o", repo="a")
    b = products.get_or_create_product(db, org="o", repo="b")
    assert repository.create_news_item(db, url="http://shared/story", title="S", product_id=a.id)
    assert repository.create_news_item(db, url="http://shared/story", title="S", product_id=b.id) is None

    _profile(db, "A", product=a)
    _profile(db, "B", product=b)
    _fake_llm(monkeypatch)
    qs = relevance.promote_relevant(db)
    assert [q.product_id for q in qs] == [a.id]  # b gets nothing
