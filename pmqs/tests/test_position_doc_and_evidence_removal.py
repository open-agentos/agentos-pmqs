"""Two dogfooding fixes:
1. Position Document fields normalize non-string LLM output (e.g. a nested
   yes/no-consequence dict) into real text instead of showing the raw Python repr,
   and render through the safe markdown subset instead of plain-escaped text.
2. The Evidence tab is removed from the Workspace view for now.
"""
from pmqs.web.render import _doc_field_text, _position_doc_html


# --- 1. dict-shaped field normalization + markdown rendering -------------------------

def test_dict_field_does_not_show_raw_python_repr():
    doc = {
        "summary": "S", "background_impact": "B", "argument_for": "F", "rebuttal_for": "RF",
        "argument_against": "A", "rebuttal_against": "RA",
        "what_your_vote_means": {
            "yes_consequence": "Ship it now.",
            "no_consequence": "Wait for the root fix.",
        },
    }
    html = _position_doc_html(doc)
    assert "yes_consequence" not in html  # no raw dict key/braces leaking through
    assert "{'yes_consequence'" not in html
    assert "Ship it now." in html
    assert "Wait for the root fix." in html
    assert "Yes consequence" in html  # readable label, not the raw key


def test_doc_field_text_handles_dict_list_and_none():
    assert _doc_field_text(None) == ""
    assert _doc_field_text("plain string") == "plain string"
    assert _doc_field_text({"a": "x", "b": "y"}) == "**A:** x\n\n**B:** y"
    assert _doc_field_text(["one", "two"]) == "- one\n- two"
    assert _doc_field_text(3) == "3"


def test_doc_sections_render_through_markdown_not_raw_escape():
    doc = {"summary": "**bold point**", "what_your_vote_means": "W", "background_impact": "B",
          "argument_for": "F", "rebuttal_for": "RF", "argument_against": "A", "rebuttal_against": "RA"}
    html = _position_doc_html(doc)
    assert "<strong>bold point</strong>" in html  # rendered, not literal asterisks
    assert "**bold point**" not in html


def test_string_fields_still_render_normally():
    doc = {"summary": "S", "what_your_vote_means": "W", "background_impact": "B",
          "argument_for": "F", "rebuttal_for": "RF", "argument_against": "A", "rebuttal_against": "RA"}
    html = _position_doc_html(doc)
    for v in ("S", "W", "B", "F", "RF", "A", "RA"):
        assert v in html


# --- 2. Evidence tab removed -----------------------------------------------------

def test_evidence_tab_not_in_template():
    from pmqs.web.render import _load_template
    t = _load_template(None)
    assert 'data-tab="evidence"' not in t
    assert 'id="tab-evidence"' not in t
    assert "['doc','chart','proposed','draft']" in t  # showTab list no longer includes it
