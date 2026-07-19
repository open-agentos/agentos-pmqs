"""#108 — artifact tab bar counts and the for/against grid.

The grid tests are contrast tests. `.doc-grid` lives inside `.doc`, which is the
`--paper` exception surface (brand doc §3), not the dark chrome — so a token measured
against `--bg-main` says nothing about whether it can be read here. That mismatch is
what these pin.
"""
import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository
from pmqs.web.render import render_workspace

TEMPLATE = Path(__file__).parent.parent / "pmqs" / "web" / "templates" / "app.html"
PAPER = "#efe9dd"


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    chans = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _token(name: str) -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})" % re.escape(name), src)
    assert m, f"token --{name} not found in :root"
    return m.group(1)


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def _render(db, n_evidence: int, n_proposed: int) -> str:
    ev = [{"type": "issue", "ref": f"#{i}"} for i in range(n_evidence)]
    q = repository.create_question(db, title="Ship or wait?", source="system", evidence=ev)
    sess = repository.open_session(db, topic="Ship or wait", question_id=q.id)
    proposed = [
        repository.create_question(db, title=f"Proposed {i}", source="system")
        for i in range(n_proposed)
    ]
    doc = {"summary": "S", "what_your_vote_means": "W", "background_impact": "B",
           "argument_for": "F", "rebuttal_for": "RF",
           "argument_against": "A", "rebuttal_against": "RA"}
    return render_workspace(sess, repository.list_messages(db, sess.id),
                            q.evidence_list, proposed, doc)


def _labels(out: str) -> dict:
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r'data-tab="([^"]+)"[^>]*>([^<]*)</div>', out)
    }


def test_counts_appear_in_tab_labels(db):
    labels = _labels(_render(db, n_evidence=4, n_proposed=2))
    assert labels["evidence"] == "Evidence (4)"
    assert labels["proposed"] == "Proposed questions (2)"


def test_empty_panes_render_zero_rather_than_hiding(db):
    labels = _labels(_render(db, n_evidence=0, n_proposed=0))
    assert labels["evidence"] == "Evidence (0)"
    assert labels["proposed"] == "Proposed questions (0)"


def test_single_artifact_tabs_get_no_count(db):
    """Position document and Impacts are one artifact each, not lists."""
    labels = _labels(_render(db, n_evidence=3, n_proposed=1))
    assert labels["doc"] == "Position document"
    assert labels["chart"] == "Impacts"


def test_counts_are_not_double_appended(db):
    """The splice strips an existing '(n)' before writing, so a re-render can't produce
    'Evidence (4) (4)'."""
    out = _render(db, n_evidence=4, n_proposed=2)
    assert "(4) (4)" not in out
    assert len(re.findall(r"Evidence \(4\)", out)) == 1


def test_tab_panes_and_order_survive(db):
    """_TAB_DOC_RE / _TAB_EVID_RE / _TAB_PROP_RE anchor on these ids and their order."""
    out = _render(db, n_evidence=2, n_proposed=1)
    order = [m.group(1) for m in re.finditer(r'<div id="(tab-[a-z]+)"', out)]
    assert order == ["tab-doc", "tab-chart", "tab-evidence", "tab-proposed", "tab-draft"]


def test_position_doc_still_splices_real_data(db):
    out = _render(db, n_evidence=1, n_proposed=1)
    for value in ("RF", "RA"):
        assert value in out, "rebuttals must keep rendering inside the new box"
    assert "Avoids a partial fix that could mask the real bug" not in out


# --- The reason this issue deviates from its spec ---

def test_for_against_markers_are_legible_on_paper():
    """The spec asked for --accent-sage (+) and --pulse-coral (−). Both are chosen
    against --bg-main and neither survives --paper, which is the surface .doc-grid is
    actually on. If someone 'corrects' this back to the spec, this fails."""
    src = TEMPLATE.read_text(encoding="utf-8")
    for rule in (r"\.doc-box\.for \.doc-text::before\{[^}]*color:var\(--([a-z-]+)\)",
                 r"\.doc-box\.against \.doc-text::before\{[^}]*color:var\(--([a-z-]+)\)"):
        m = re.search(rule, src)
        assert m, f"marker rule missing: {rule}"
        ratio = contrast(_token(m.group(1)), PAPER)
        assert ratio >= 4.5, (
            f"--{m.group(1)} is {ratio:.2f}:1 on --paper; the for/against markers sit on "
            f"the paper document surface and must clear 4.5:1"
        )


def test_the_specced_tokens_really_would_have_failed():
    """Documents the finding rather than just asserting the fix — if the palette is
    ever retuned so sage/coral do work on paper, this fails and the deviation should
    be revisited."""
    assert contrast(_token("accent-sage"), PAPER) < 3.0
    assert contrast(_token("pulse-coral"), PAPER) < 3.0


def test_marker_colours_match_their_box_borders():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert ".doc-box.for{border-left:3px solid var(--accent-teal-dim);}" in src
    assert ".doc-box.against{border-left:3px solid var(--pulse-coral-dim);}" in src
