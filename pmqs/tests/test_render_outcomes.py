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
