"""test_outcome_receipt.py — the receipt answers 'where did it go?' (Wave 1)."""
from pmqs.outcomes.receipt import display_title, location_for


def test_issue_location_is_the_github_ref():
    loc = location_for("issue", github_ref="https://github.com/o/r/issues/7")
    assert loc["kind"] == "github"
    assert loc["url"] == "https://github.com/o/r/issues/7"
    assert "GitHub" in loc["label"]


def test_hosted_types_resolve_to_the_ledger():
    for t in ("policy", "document", "meeting", "question"):
        loc = location_for(t)
        assert loc["kind"] == "ledger"
        assert loc["url"] == "/outcomes"


def test_ledger_url_respects_workspace_prefix():
    loc = location_for("document", prefix="/w/acme")
    assert loc["url"] == "/w/acme/outcomes"


def test_issue_without_ref_falls_back_to_ledger():
    # A location must always link somewhere; never a dead receipt.
    loc = location_for("issue", github_ref=None)
    assert loc["kind"] == "ledger"
    assert loc["url"].endswith("/outcomes")


def test_display_title_uses_title_field():
    assert display_title("document", {"title": "Drift brief"}) == "Drift brief"
    assert display_title("meeting", {"title": "Roadmap review"}) == "Roadmap review"


def test_policy_display_title_is_its_text_truncated():
    assert display_title("policy", {"text": "cap retries at 3"}) == "cap retries at 3"
    long = "x" * 200
    out = display_title("policy", {"text": long})
    assert out.endswith("…") and len(out) <= 80
