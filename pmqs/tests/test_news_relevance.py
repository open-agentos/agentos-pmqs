from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, settings
import pmqs.news.relevance as relevance


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def _seed(db, n=3):
    for i in range(n):
        repository.create_news_item(db, url=f"http://x/{i}", title=f"News {i}",
                                    source_label="pub.example", summary="s", published_at="2026-07-14")


def test_promote_empty_when_llm_off(db, monkeypatch):
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: False)
    _seed(db)
    assert relevance.promote_relevant(db) == []


def test_relevant_items_become_news_questions(db, monkeypatch):
    _seed(db, 3)
    settings.set_news_config(db, product_profile="PMQs", top_n=3, min_relevance=0.5)
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
    settings.set_news_config(db, product_profile="P", top_n=2, min_relevance=0.3)
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
    settings.set_news_config(db, product_profile="P", top_n=3, min_relevance=0.8)
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
    settings.set_news_config(db, product_profile="P", top_n=3, min_relevance=0.1)
    monkeypatch.setattr(relevance.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(relevance.llm, "complete_json",
                        lambda s, u, **k: {"items": [{"index": 0, "relevance": 0.9, "title": "T", "description": "d"}]})
    qs = relevance.promote_relevant(db)
    # news evidence must be a citation, never a github ref
    ev = qs[0].evidence_list[0]
    assert "github" not in str(ev).lower()
