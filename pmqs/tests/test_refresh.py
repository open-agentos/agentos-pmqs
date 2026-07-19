"""Tests for pmqs.refresh — one Inbox Refresh across every data source, with a
specific, legible reason for whatever each source produced (esp. zero)."""
import os
from datetime import datetime, timedelta, timezone

os.environ["PMQS_LLM_MODE"] = "off"  # framing/dedup/relevance degrade to stubs

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs import products, repository, settings
from pmqs.agentos_client import AgentOSClientError
from pmqs.db import Base
from pmqs.refresh import RefreshReport, SourceResult, refresh_all


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


class _State:
    def __init__(self, state):
        self._state = state

    def __call__(self, *a, **k):
        return self

    def get_state(self):
        return self._state


def _patch_repo(monkeypatch, *, state=None, error=None):
    import pmqs.refresh as R

    class _Client:
        def __init__(self, *a, **k):
            pass

        def get_state(self):
            if error is not None:
                raise AgentOSClientError(error)
            return state or {"issues": [], "labels": []}

    monkeypatch.setattr(R, "AgentOSClient", _Client)


# ------------------------------------------------------------------ report codec
def test_report_encodes_and_decodes():
    rep = RefreshReport(SourceResult("generated", 2, "x"), SourceResult("no_key", 0, "set K"))
    back = RefreshReport.decode(rep.encode())
    assert back.repo.code == "generated" and back.repo.count == 2
    assert back.news.code == "no_key" and back.news.detail == "set K"
    assert back.total == 2


def test_decode_tolerates_garbage():
    assert RefreshReport.decode("") is None
    assert RefreshReport.decode("@@@not-base64@@@") is None


# ------------------------------------------------------------------ repo source
def test_clean_repo_is_explained_not_silent(db, monkeypatch):
    products.get_or_create_default_product(db)
    _patch_repo(monkeypatch, state={"issues": [{"number": 1, "state": "open",
                                                "updatedAt": datetime.now(timezone.utc).isoformat()}],
                                     "labels": []})
    rep = refresh_all(db)
    assert rep.repo.code == "clean"
    assert "scanned 1 open issue" in rep.repo.detail
    assert "none stale" in rep.repo.detail


def test_repo_error_surfaces_instead_of_crashing(db, monkeypatch):
    products.get_or_create_default_product(db)
    _patch_repo(monkeypatch, error="gh command failed: not authenticated")
    rep = refresh_all(db)
    assert rep.repo.code == "error"
    assert "not authenticated" in rep.repo.detail  # the gh message reaches the PM


def test_stale_issue_generates_a_question(db, monkeypatch):
    products.get_or_create_default_product(db)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    _patch_repo(monkeypatch, state={
        "issues": [{"number": 42, "title": "old thing", "state": "open",
                    "updatedAt": old, "url": "http://x/42", "labels": []}],
        "labels": [],
    })
    rep = refresh_all(db)
    assert rep.repo.code == "generated"
    assert rep.repo.count >= 1


# ------------------------------------------------------------------ news source
def test_news_disabled_is_named(db, monkeypatch):
    products.get_or_create_default_product(db)
    settings.set_news_config(db, enabled=False, api_key_raw="k")
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "disabled"


def test_news_missing_key_names_the_env_var(db, monkeypatch):
    products.get_or_create_default_product(db)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "no_key"
    assert "BRAVE_API_KEY" in rep.news.detail


def test_news_empty_watchlist_is_named(db, monkeypatch):
    products.get_or_create_default_product(db)
    settings.set_news_config(db, api_key_raw="k")  # key present, but no watchlist terms
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "no_watchlist"


def test_news_llm_off_is_distinct_from_nothing_relevant(db, monkeypatch):
    p = products.get_or_create_default_product(db)
    settings.set_news_config(db, api_key_raw="k")
    products.set_news_config(db, p, watchlist={"keywords": ["agents"]})
    # ingest "fetched" two items; LLM is off so they can't be judged.
    import pmqs.news.fetch as F
    import pmqs.refresh as R
    monkeypatch.setattr(F, "ingest", lambda db, cfg=None: [object(), object()])
    monkeypatch.setattr(R.llm, "is_enabled", lambda: False)
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "fetched_llm_off"
    assert "fetched 2" in rep.news.detail
    # the run is still stamped so Settings' status line reflects the attempt
    assert settings.get_news_config(db)["last_run"]


def test_news_promoted_reports_count(db, monkeypatch):
    p = products.get_or_create_default_product(db)
    settings.set_news_config(db, api_key_raw="k")
    products.set_news_config(db, p, watchlist={"keywords": ["agents"]})
    import pmqs.news.fetch as F
    import pmqs.news.relevance as REL
    import pmqs.refresh as R
    from pmqs.news.relevance import NewsDiag
    monkeypatch.setattr(R.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(F, "ingest", lambda db, cfg=None: [object()])
    monkeypatch.setattr(REL, "promote_relevant_reported",
                        lambda db, cfg=None: ([object(), object(), object()], NewsDiag(judged=3, promoted=3)))
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "promoted"
    assert rep.news.count == 3
    assert rep.total >= 3


def test_news_nothing_relevant_shows_the_top_score(db, monkeypatch):
    p = products.get_or_create_default_product(db)
    settings.set_news_config(db, api_key_raw="k", min_relevance=0.9)
    products.set_news_config(db, p, watchlist={"keywords": ["agents"]})
    import pmqs.news.fetch as F
    import pmqs.news.relevance as REL
    import pmqs.refresh as R
    from pmqs.news.relevance import NewsDiag
    monkeypatch.setattr(R.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(F, "ingest", lambda db, cfg=None: [])
    # judged 8, best item only reached 0.42 — below the 0.9 bar
    monkeypatch.setattr(REL, "promote_relevant_reported",
                        lambda db, cfg=None: ([], NewsDiag(judged=8, top_relevance=0.42, products_with_items=1)))
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "nothing_relevant"
    assert "judged 8" in rep.news.detail
    assert "0.42" in rep.news.detail          # the top score, so the PM can tune the bar


def test_news_missing_profile_is_called_out(db, monkeypatch):
    p = products.get_or_create_default_product(db)
    settings.set_news_config(db, api_key_raw="k")
    products.set_news_config(db, p, watchlist={"keywords": ["agents"]})
    import pmqs.news.fetch as F
    import pmqs.news.relevance as REL
    import pmqs.refresh as R
    from pmqs.news.relevance import NewsDiag
    monkeypatch.setattr(R.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(F, "ingest", lambda db, cfg=None: [object()])
    # items judged, but the (only) product with items had no profile to judge against
    monkeypatch.setattr(REL, "promote_relevant_reported",
                        lambda db, cfg=None: ([], NewsDiag(judged=5, products_with_items=1, products_missing_profile=1)))
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "no_profile"       # actionable cause, not a flat "nothing relevant"


def test_news_llm_error_is_not_disguised_as_nothing_relevant(db, monkeypatch):
    p = products.get_or_create_default_product(db)
    settings.set_news_config(db, api_key_raw="k")
    products.set_news_config(db, p, watchlist={"keywords": ["agents"]})
    import pmqs.news.fetch as F
    import pmqs.news.relevance as REL
    import pmqs.refresh as R
    from pmqs.news.relevance import NewsDiag
    monkeypatch.setattr(R.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(F, "ingest", lambda db, cfg=None: [object()])
    # the relevance call failed on every chunk → judged nothing
    monkeypatch.setattr(REL, "promote_relevant_reported",
                        lambda db, cfg=None: ([], NewsDiag(judged=0, llm_error="Expecting value: line 1", products_with_items=1)))
    _patch_repo(monkeypatch)
    rep = refresh_all(db)
    assert rep.news.code == "news_llm_error"
    assert "Expecting value" in rep.news.detail
