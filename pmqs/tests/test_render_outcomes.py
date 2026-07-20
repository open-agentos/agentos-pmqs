from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository
from pmqs.web.render import render_outcomes


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_real_outcomes_replace_fixtures(db):
    repository.create_outcome(db, type="policy", payload={"text": "never ship fridays"})
    repository.create_outcome(db, type="document", payload={"title": "Drift brief", "body": "b"})
    out = render_outcomes(db)
    import re
    m = re.search(r'<div id="outcomes-list">(.*?)</div>\s*</div>\s*</div>\s*</div>\s*</div>', out, re.DOTALL)
    region = m.group(1)
    assert "never ship fridays" in region
    assert "Drift brief" in region
    # mockup fixtures gone from the ledger
    assert "Mitigate #47" not in region
    assert "Competitive brief" not in region
    # inbox view preserved (no regression)
    assert 'id="view-inbox"' in out


def test_summary_counts_reflect_real_rows(db):
    repository.create_outcome(db, type="policy", payload={"text": "p"})
    repository.create_outcome(db, type="policy", payload={"text": "p2"})
    repository.create_outcome(db, type="issue", payload={"title": "i"}, github_ref="http://x/1")
    out = render_outcomes(db)
    import re
    assert re.search(r'sum-policy">(\d+)', out).group(1) == "2"
    assert re.search(r'sum-issue">(\d+)', out).group(1) == "1"
    assert re.search(r'sum-document">(\d+)', out).group(1) == "0"


def test_empty_outcomes_shows_placeholder(db):
    out = render_outcomes(db)
    assert "No outcomes yet" in out


def test_issue_ledger_item_shows_github_ref(db):
    repository.create_outcome(db, type="issue", payload={"title": "i"},
                              github_ref="https://github.com/o/r/issues/9")
    out = render_outcomes(db)
    assert "issues/9" in out


def test_policy_ledger_item_never_shows_github(db):
    repository.create_outcome(db, type="policy", payload={"text": "private rule"})
    out = render_outcomes(db)
    import re
    m = re.search(r'<div id="outcomes-list">(.*?)</div>\s*</div>\s*</div>\s*</div>\s*</div>', out, re.DOTALL)
    region = m.group(1)
    # the policy row must not carry any github link
    assert "github.com" not in region


# --- Wave 2 item 5: authorship display + visibility-filtered ledger ---

def test_ledger_rows_show_their_author(db):
    """"Each row shows its author" (item 5 acceptance). The ledger is Product-wide, so a
    row may be a colleague's -- "who decided this" is half the point of sharing it."""
    from pmqs import members
    from pmqs.models import Member

    members.get_or_create_default_member(db)  # the account owner exists first
    colleague = Member(display_name="Ada")
    db.add(colleague)
    db.commit()
    session = repository.open_session(db, topic="q", author_member_id=colleague.id)
    repository.create_outcome(db, type="policy", payload={"text": "never ship fridays"},
                              session_id=session.id, author_member_id=colleague.id)

    out = render_outcomes(db)
    assert "Ada" in out


def test_ledger_hides_another_members_private_room(db):
    """The renderer must apply §4's visibility resolution, not just product scope."""
    from pmqs import members
    from pmqs.models import Member

    members.get_or_create_default_member(db)  # the viewer -- must exist before Ada
    colleague = Member(display_name="Ada")
    db.add(colleague)
    db.commit()
    private = repository.open_session(db, topic="q", author_member_id=colleague.id,
                                      visibility="private")
    repository.create_outcome(db, type="policy", payload={"text": "SECRET private policy"},
                              session_id=private.id, author_member_id=colleague.id)

    out = render_outcomes(db)
    assert "SECRET private policy" not in out


def test_author_name_is_escaped(db):
    from pmqs import members
    from pmqs.models import Member

    members.get_or_create_default_member(db)
    nasty = Member(display_name='<script>alert(1)</script>')
    db.add(nasty)
    db.commit()
    session = repository.open_session(db, topic="q", author_member_id=nasty.id)
    repository.create_outcome(db, type="policy", payload={"text": "p"},
                              session_id=session.id, author_member_id=nasty.id)

    out = render_outcomes(db)
    assert "<script>alert(1)</script>" not in out


def test_ledger_document_has_export_link(db):
    from pmqs.web.render import render_outcomes
    repository.create_outcome(db, type="document", payload={"title": "Brief", "body": "b"})
    out = render_outcomes(db)
    assert "export.md" in out
    assert "Download .md" in out          # Wave 3 route row (replaced "Export .md")
    assert "Copy as Markdown" in out


def test_ledger_meeting_shows_calendar_when_present(db):
    from pmqs.web.render import render_outcomes
    repository.create_outcome(
        db, type="meeting",
        payload={"title": "Review", "agenda": "x", "calendar_link": "https://cal/x"},
    )
    out = render_outcomes(db)
    assert "Add to Google Calendar" in out   # live no-auth deep link (Wave 3)
    assert "https://cal/x" in out            # the pasted event link is also offered
