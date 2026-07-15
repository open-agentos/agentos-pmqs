import pytest

from pmqs.outcomes.types import (
    OutcomeValidationError,
    build_policy,
    build_document,
    build_meeting,
    build_question,
    context_text,
    DURABLE_TYPES,
)


def test_build_policy_requires_text():
    with pytest.raises(OutcomeValidationError):
        build_policy("")
    assert build_policy("cap retries at 3") == {"text": "cap retries at 3"}


def test_build_document_requires_title():
    with pytest.raises(OutcomeValidationError):
        build_document("")
    d = build_document("Drift briefing", "body text")
    assert d == {"title": "Drift briefing", "body": "body text"}


def test_build_meeting_fields():
    m = build_meeting("Review #47", "1. context\n2. decide", "https://cal/x")
    assert m == {"title": "Review #47", "agenda": "1. context\n2. decide", "calendar_link": "https://cal/x"}
    # calendar_link optional
    m2 = build_meeting("Sync")
    assert m2["calendar_link"] == ""


def test_build_question_requires_title():
    with pytest.raises(OutcomeValidationError):
        build_question("")
    assert build_question("Should we?")["title"] == "Should we?"


def test_durable_types_excludes_issue_and_question():
    assert DURABLE_TYPES == {"policy", "document", "meeting"}


def test_context_text_rendering():
    assert context_text("policy", {"text": "always X"}) == "always X"
    assert "Doc" in context_text("document", {"title": "Doc", "body": "b"})
    assert "Mtg" in context_text("meeting", {"title": "Mtg", "agenda": "a"})
    assert context_text("issue", {}) == ""  # non-durable → no context text
