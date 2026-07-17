"""#111 — one source-card builder, two styles.

The value of this refactor is only realised if the Evidence tab is genuinely unchanged,
so most of these tests are that assertion. The golden strings below were captured from
the pre-refactor `_evidence_html` on main.
"""
import re

import pytest

from pmqs.web.render import _evidence_html, source_card_html, question_detail_html


def _norm(s: str) -> str:
    """HTML-insignificant whitespace only. The refactor drops a trailing space the old
    builder emitted before an empty link; nothing renders differently."""
    return re.sub(r"\s+", " ", s).replace("> <", "><").strip()


# Captured from _evidence_html on main, before the refactor.
GOLDEN = [
    (
        [{"type": "issue", "ref": "#47", "url": "http://x/47"}],
        '<div class="evidence-item"><div class="evidence-title">issue #47</div>'
        '<div class="evidence-sub">http://x/47</div></div>',
    ),
    (
        [{"type": "pr", "ref": "#55"}],
        '<div class="evidence-item"><div class="evidence-title">pr #55</div>'
        '<div class="evidence-sub"></div></div>',
    ),
    (
        [{"type": "news", "source": "The Verge", "title": "Oak ships state --json",
          "date": "2026-07-01", "url": "http://v/1"}],
        '<div class="evidence-item"><div class="evidence-title">\u201cOak ships state --json\u201d</div>'
        '<div class="evidence-sub">reportedly, via The Verge \u00b7 2026-07-01 '
        '<a href="http://v/1">http://v/1</a></div></div>',
    ),
    (
        [{"type": "run", "ref": "r-12", "url": ""}],
        '<div class="evidence-item"><div class="evidence-title">run r-12</div>'
        '<div class="evidence-sub"></div></div>',
    ),
]


@pytest.mark.parametrize("evidence,expected", GOLDEN)
def test_evidence_tab_is_unchanged(evidence, expected):
    assert _norm(_evidence_html(evidence)) == _norm(expected)


def test_evidence_empty_state_unchanged():
    assert _evidence_html([]) == (
        '<div class="evidence-item"><div class="evidence-title">No evidence bound yet.</div></div>'
    )


def test_evidence_keeps_its_contract_class_names():
    """.evidence-item / .evidence-title / .evidence-sub are TEMPLATE-CONTRACT §4."""
    out = _evidence_html([{"type": "issue", "ref": "#47"}])
    for cls in ("evidence-item", "evidence-title", "evidence-sub"):
        assert f'class="{cls}"' in out
    for cls in ("source-card", "source-ref", "source-meta"):
        assert cls not in out


def test_detail_style_keeps_its_own_class_names():
    out = source_card_html({"type": "issue", "ref": "#47"})
    for cls in ("source-card", "source-ref", "source-meta"):
        assert f'class="{cls}"' in out
    assert "evidence-item" not in out


def test_both_styles_render_the_same_object_from_one_builder():
    e = {"type": "news", "source": "The Verge", "title": "Oak ships", "date": "2026-07-01",
         "url": "http://v/1"}
    detail = source_card_html(e, style="detail")
    evidence = source_card_html(e, style="evidence")
    for probe in ("\u201cOak ships\u201d", "reportedly, via The Verge", "2026-07-01",
                  '<a href="http://v/1">'):
        assert probe in detail and probe in evidence


def test_link_refs_is_the_one_real_difference():
    """Preserved deliberately: the Evidence tab shows a repo ref's URL as plain text
    while linking a news URL. That predates #111, which is scoped as a pure refactor."""
    e = {"type": "issue", "ref": "#47", "url": "http://x/47"}
    assert '<a href="http://x/47">' in source_card_html(e, style="detail")
    assert "<a href=" not in source_card_html(e, style="evidence")
    # ...but news links in BOTH, which is the inconsistency.
    news = {"type": "news", "source": "V", "title": "T", "url": "http://v/1"}
    assert '<a href="http://v/1">' in source_card_html(news, style="evidence")


def test_unknown_style_raises():
    with pytest.raises(ValueError, match="unknown source-card style"):
        source_card_html({"type": "issue", "ref": "#1"}, style="nope")


def test_detail_pane_uses_the_shared_builder():
    class Q:
        id = "q1"
        title = "Ship or wait?"
        description = "Some context"
        lens_tags_list = ["risk_exposure"]
        evidence_list = [{"type": "issue", "ref": "#47", "url": "http://x/47"}]
        created_at = None
    out = question_detail_html(Q())
    assert 'class="source-card"' in out
    assert "issue #47" in out


def test_escaping_survives_both_styles():
    e = {"type": "news", "source": "<b>V</b>", "title": "a & b <script>",
         "url": "http://v/?a=1&b=2"}
    for style in ("detail", "evidence"):
        out = source_card_html(e, style=style)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
        assert "<b>V</b>" not in out
