"""#107 — two-pane Inbox.

These tests exist because the suite is otherwise blind to the thing most likely to
break here. TEMPLATE-CONTRACT.md is explicit: render.py splices by regex, no test
asserts on the markup, and a failed splice serves fixture content with CI green.
So assert on the splice itself, not just that a function returned a string.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository
from pmqs.web.render import render_inbox

# Fixture copy that must never survive a successful splice.
FIXTURE_TITLES = [
    "Ship a mitigation now, or keep blocking on the adopt",
    "PR #55 and #56 are both green",
    "What is Oak doing with a state --json equivalent",
    "Error-loop spend is still ~40% of weekly cost",
    "Revisit the LLM provider cost model",
]


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def questions(db):
    repository.create_question(
        db, title="Ship the adopt mitigation, or hold for the root fix?",
        source="system", description="The mitigation only covers the adopt path.",
        evidence=[{"type": "issue", "ref": "#47", "url": "http://x/47"}],
        lens_tags=["risk_exposure"],
    )
    repository.create_question(db, title="Match the Oak state --json equivalent?", source="pm")
    return repository.list_questions(db)


def test_inbox_splices_real_titles_not_fixtures(questions):
    out = render_inbox(questions)
    assert "Ship the adopt mitigation, or hold for the root fix?" in out
    assert "Match the Oak state --json equivalent?" in out
    for fixture in FIXTURE_TITLES:
        assert fixture not in out, f"fixture content survived the splice: {fixture!r}"


def test_both_cards_sentinels_survive(questions):
    """The sentinels are the anchor now. If a restyle drops one, _CARDS_REGION_RE stops
    matching and render_inbox raises — but only if the sentinels are still a pair."""
    out = render_inbox(questions)
    assert "<!-- INBOX CARDS -->" in out
    assert "<!-- /INBOX CARDS -->" in out


def test_splice_stays_inside_the_sentinels(questions):
    """Regression for the anchor this issue replaced: the old </div>-counting regex ran
    from quick-add to <!-- WORKSPACE VIEW -->, so group 2 swallowed every view in
    between. Once #view-workspaces landed, rendering the Inbox deleted it."""
    out = render_inbox(questions)
    assert 'id="view-workspaces"' in out
    assert 'id="view-workspace"' in out
    assert "<!-- WORKSPACE VIEW -->" in out
    cards = out[out.index("<!-- INBOX CARDS -->"):out.index("<!-- /INBOX CARDS -->")]
    assert 'id="view-workspaces"' not in cards


def test_detail_pane_is_shipped_for_every_question(questions):
    out = render_inbox(questions)
    assert 'id="inbox-detail"' in out
    assert 'id="pmqs-question-detail"' in out
    for q in questions:
        assert q.id in out
    # The description is what the detail pane adds over the card.
    assert "The mitigation only covers the adopt path." in out


def test_card_click_selects_and_sword_still_navigates(questions):
    out = render_inbox(questions)
    assert "pmqsSelect(" in out
    assert "pmqsOpenWorkspace(" in out, "the ⚔ button must keep the old navigate path"


def test_empty_inbox_renders_empty_state_not_fixtures(db):
    out = render_inbox([])
    assert "Your Inbox is empty." in out
    for fixture in FIXTURE_TITLES:
        assert fixture not in out


def test_detail_html_cannot_close_the_script_tag(db):
    """The payload is embedded in a <script> block, so a title containing '</script>'
    must not be able to break out of it."""
    repository.create_question(db, title="Why does </script><b>x</b> break?", source="pm")
    out = render_inbox(repository.list_questions(db))
    blob = out[out.index('id="pmqs-question-detail"'):]
    blob = blob[:blob.index("</script>")]
    assert "</script>" not in blob
    assert "<\\/script>" in blob or "<\\/" in blob
