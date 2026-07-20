"""Scope B of docs/build-spec-optional-repo-onramp.md: a website-only product has no
structural source. Refresh and seed must skip it entirely — zero `gh` calls — and never
fall through to config.AGENTOS_REPO (§5). The banner says so neutrally, not as an error.
"""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs import products
from pmqs.db import Base
from pmqs.refresh import refresh_all


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


class _CountingClient:
    """Records every instantiation so a test can prove the repo pass was skipped."""
    calls = 0

    def __init__(self, *a, **k):
        type(self).calls += 1
        self.repo = k.get("repo")

    def get_state(self):
        return {"issues": [], "labels": []}


def _patch(monkeypatch):
    import pmqs.refresh as R
    _CountingClient.calls = 0
    monkeypatch.setattr(R, "AgentOSClient", _CountingClient)


# --- refresh -------------------------------------------------------------------------

def test_repo_less_product_skips_structural_pass(db, monkeypatch):
    _patch(monkeypatch)
    p = products.get_or_create_product(db, website="https://acme.example", display_name="Acme")

    rep = refresh_all(db, product_id=p.id, repo=p.full_name)  # full_name is "" here

    assert rep.repo.code == "no_repo"
    assert _CountingClient.calls == 0  # the whole point: no gh call for a website-only product


def test_repo_backed_product_still_runs_structural_pass(db, monkeypatch):
    _patch(monkeypatch)
    p = products.get_or_create_product(db, org="open-agentos", repo="agentos")

    rep = refresh_all(db, product_id=p.id, repo=p.full_name)

    assert rep.repo.code in ("clean", "generated")  # it actually ran
    assert _CountingClient.calls == 1


def test_legacy_unprefixed_mount_still_defaults(db, monkeypatch):
    _patch(monkeypatch)
    # product_id=None is the legacy unprefixed mount -- must keep defaulting to the
    # configured repo, NOT be mistaken for "no repo".
    rep = refresh_all(db, product_id=None, repo=None)
    assert rep.repo.code in ("clean", "generated")
    assert _CountingClient.calls == 1


# --- seed ----------------------------------------------------------------------------

def test_seed_workspace_skips_repo_less_product(db, monkeypatch):
    import pmqs.pipeline as P

    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("seed must not build a client for a repo-less product")

    monkeypatch.setattr(P, "AgentOSClient", _Boom, raising=False)
    p = products.get_or_create_product(db, website="https://acme.example", display_name="Acme")
    assert P.seed_workspace(db, p) == []  # no exception -> no client built


# --- banner --------------------------------------------------------------------------

def test_no_repo_banner_is_neutral_not_amber():
    from pmqs.web.render import _refresh_line, _REPO_LINES
    from pmqs.refresh import SourceResult

    kind, text = _refresh_line(_REPO_LINES, SourceResult("no_repo"))
    assert kind == "ok"  # teal / working-as-intended, not a fixable-error amber
    assert "connect" in text.lower()  # invites attaching one (§14.4)
