"""test_routing.py — where an outcome can go (Wave 3).

The seam is honest: live destinations (copy/download/open, GitHub for a pushed issue, a
Google Calendar deep link for a meeting) are available and carry a url/action; Slack /
Notion / Jira are stubs — present so the PM sees the intent, disabled until wired.
"""
import os
from urllib.parse import parse_qs, urlparse

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs.db import Base
from pmqs import repository
from pmqs.outcomes.routing import Destination, destinations_for, gcal_template_link


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def _keys(dests):
    return [d.key for d in dests]


def _by_key(dests, key):
    return next(d for d in dests if d.key == key)


# --- the Google Calendar deep link is real, not a stub ---

def test_gcal_link_encodes_title_and_agenda():
    url = gcal_template_link("Roadmap review", "cover the drift bug")
    p = urlparse(url)
    assert p.netloc == "calendar.google.com"
    q = parse_qs(p.query)
    assert q["action"] == ["TEMPLATE"]
    assert q["text"] == ["Roadmap review"]
    assert q["details"] == ["cover the drift bug"]


# --- per-type destination sets ---

def test_document_offers_copy_download_open_and_stub_tools(db):
    o = repository.create_outcome(db, type="document", payload={"title": "Brief", "body": "b"})
    dests = destinations_for(o, {"title": "Brief", "body": "b"})
    assert _keys(dests)[:3] == ["copy", "download", "open"]
    for d in dests:
        assert d.available is (d.kind != "stub")
    notion = _by_key(dests, "notion")
    assert notion.kind == "stub" and notion.available is False and notion.hint


def test_meeting_has_live_gcal_link(db):
    o = repository.create_outcome(db, type="meeting", payload={"title": "Review", "agenda": "x"})
    dests = destinations_for(o, {"title": "Review", "agenda": "x"})
    gcal = _by_key(dests, "gcal")
    assert gcal.available is True and gcal.kind == "link"
    assert "calendar.google.com" in gcal.url
    # no pasted calendar_link -> no 'event' destination
    assert "event" not in _keys(dests)


def test_meeting_adds_pasted_event_link_when_present(db):
    payload = {"title": "Review", "agenda": "x", "calendar_link": "https://cal/abc"}
    o = repository.create_outcome(db, type="meeting", payload=payload)
    dests = destinations_for(o, payload)
    assert _by_key(dests, "event").url == "https://cal/abc"


def test_issue_github_available_only_after_push(db):
    o = repository.create_outcome(db, type="issue", payload={"title": "bug"}, github_ref=None)
    gh = _by_key(destinations_for(o, {"title": "bug"}), "github")
    assert gh.available is False and gh.hint  # not pushed yet

    o2 = repository.create_outcome(db, type="issue", payload={"title": "bug2"},
                                   github_ref="https://github.com/o/r/issues/9")
    gh2 = _by_key(destinations_for(o2, {"title": "bug2"}), "github")
    assert gh2.available is True and gh2.url.endswith("/issues/9")


def test_every_type_can_at_least_be_copied(db):
    for t, payload in [
        ("document", {"title": "d"}), ("meeting", {"title": "m"}),
        ("policy", {"text": "p"}), ("question", {"title": "q"}),
        ("issue", {"title": "i"}),
    ]:
        o = repository.create_outcome(db, type=t, payload=payload)
        keys = _keys(destinations_for(o, payload))
        assert "copy" in keys, f"{t} has no copy destination"


def test_stubs_carry_a_hint_and_are_unavailable(db):
    o = repository.create_outcome(db, type="question", payload={"title": "q"})
    slack = _by_key(destinations_for(o, {"title": "q"}), "slack")
    assert slack.kind == "stub" and slack.available is False
    assert "coming soon" in slack.hint.lower()


# --- rendered ledger row ---

def test_ledger_row_renders_live_buttons_and_disabled_stub(db):
    from pmqs.web.render import render_outcomes
    repository.create_outcome(db, type="document", payload={"title": "Brief", "body": "b"})
    out = render_outcomes(db)
    assert 'onclick="pmqsRoute(this)"' in out       # live button wired
    assert 'data-kind="copy"' in out
    assert 'class="l-btn stub" disabled' in out      # Notion/Slack disabled, visible
    assert "Send to Notion" in out
