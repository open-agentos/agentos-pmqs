import datetime as dt

from pmqs.triggers.stale_issue_age import StaleIssueAgeTrigger
from pmqs.triggers.label_conflicts import LabelConflictsTrigger


def _iso(days_ago):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


def _state():
    return {
        "issues": [
            {"number": 42, "title": "old thing", "url": "u/42", "state": "open",
             "updatedAt": _iso(40), "createdAt": _iso(60), "labels": []},
            {"number": 7, "title": "fresh", "url": "u/7", "state": "open",
             "updatedAt": _iso(1), "createdAt": _iso(2), "labels": []},
            {"number": 9, "title": "conflicted", "url": "u/9", "state": "open",
             "updatedAt": _iso(1), "createdAt": _iso(1),
             "labels": [{"name": "status:blocked"}, {"name": "status:in-progress"}]},
        ]
    }


def test_stale_issue_produces_exactly_one_question():
    hits = StaleIssueAgeTrigger(age_days=14).run(_state())
    assert len(hits) == 1
    assert hits[0]["ref"] == "#42"
    assert hits[0]["lens_tags"] == ["quality_reliability"]
    assert hits[0]["evidence"][0]["url"] == "u/42"


def test_stale_threshold_respected():
    assert StaleIssueAgeTrigger(age_days=100).run(_state()) == []


def test_label_conflict_detected():
    hits = LabelConflictsTrigger().run(_state())
    assert len(hits) == 1
    assert hits[0]["ref"] == "#9"
    assert hits[0]["lens_tags"] == ["risk_exposure"]


def test_no_conflict_when_labels_clean():
    state = {"issues": [{"number": 1, "state": "open", "labels": [{"name": "status:todo"}]}]}
    assert LabelConflictsTrigger().run(state) == []
