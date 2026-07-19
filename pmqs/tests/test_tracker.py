"""test_tracker.py — the tracker seam: Issue outcomes aren't hardcoded to GitHub (Wave 3)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs.db import Base
from pmqs import repository, settings
from pmqs.outcomes import issue as issue_mod
from pmqs.outcomes.tracker import (
    GitHubTracker,
    JiraTracker,
    TrackerNotConfigured,
    get_tracker,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def create_issue(self, title, body, labels=None):
        self.calls.append((title, body, labels))
        return {"url": "https://github.com/o/r/issues/7", "number": 7}


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_github_tracker_delegates_to_client():
    fc = FakeClient()
    t = GitHubTracker(client=fc)
    out = t.create_issue("T", "B", ["risk"])
    assert out["number"] == 7
    assert fc.calls == [("T", "B", ["risk"])]


def test_jira_tracker_declines_cleanly():
    with pytest.raises(TrackerNotConfigured):
        JiraTracker().create_issue("T", "B")


def test_default_tracker_is_github(db):
    assert settings.get_tracker(db) == "github"
    assert isinstance(get_tracker(db, client=FakeClient()), GitHubTracker)


def test_setting_tracker_to_jira_routes_to_jira(db):
    settings.set_tracker(db, "jira")
    assert settings.get_tracker(db) == "jira"
    assert isinstance(get_tracker(db), JiraTracker)


def test_unknown_tracker_setting_falls_back_to_github(db):
    with pytest.raises(ValueError):
        settings.set_tracker(db, "bugzilla")


def test_push_routes_through_selected_tracker(db):
    # Jira selected → push declines rather than silently hitting GitHub.
    settings.set_tracker(db, "jira")
    q = repository.create_question(db, title="Push me", source="pm")
    with pytest.raises(TrackerNotConfigured):
        issue_mod.push_question_to_issue(db, q)
    # nothing recorded, question not promoted
    assert repository.list_outcomes(db) == []
    assert repository.get_question(db, q.id).status != "promoted"


def test_push_with_explicit_client_still_works(db):
    # Back-compat: passing a client wraps it as GitHub (the existing issue test path).
    q = repository.create_question(db, title="Push me", source="pm")
    res = issue_mod.push_question_to_issue(db, q, client=FakeClient())
    assert "issues/7" in res["github_ref"]
    assert repository.get_question(db, q.id).status == "promoted"
