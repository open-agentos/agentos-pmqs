"""Tests for the logo socket (web/logo.py + web/assets/logo-mark.svg).

Brand doc §2 is still open — the per-facet bevel is coming. These tests pin the
things that must survive a re-cut of the geometry, and deliberately do NOT pin
the facet coordinates, which the design agent is expected to change.
"""

import re

import pytest

from pmqs import config
from pmqs.web import logo
from pmqs.web.render import render_inbox


def _polys(group_id: str) -> list[str]:
    svg = logo.MARK_PATH.read_text(encoding="utf-8")
    body = svg.split(f'id="{group_id}"', 1)[1].split("</g>", 1)[0]
    return re.findall(r'points="([^"]+)"', body)


def test_mark_has_tight_square_viewbox():
    """The reference draft used viewBox 0 0 680 520 for artwork occupying only
    ~18% of it. As an asset that makes the mark render small and off-centre in
    any fixed box."""
    svg = logo.mark_svg()
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    x, y, w, h = (float(v) for v in vb.split())
    assert w == h, f"the mark is square; viewBox is not: {vb}"
    assert (w, h) == (252.0, 252.0)


def test_design_agent_comments_do_not_ship():
    """The .svg carries a long brief for the design agent. It should not be
    served to every visitor on every page."""
    assert "DESIGN AGENT" in logo.MARK_PATH.read_text(encoding="utf-8")
    assert "DESIGN AGENT" not in logo.mark_svg()
    assert "<!--" not in logo.mark_svg()


def test_tail_has_exactly_eight_facets():
    """§2: one facet per analytical lens. Eight perspectives narrowing to one
    point of resolution. If a re-cut changes this, it should be deliberate."""
    assert len(_polys("tail")) == 8


def test_ring_has_eleven_facets():
    assert len(_polys("ring")) == 11


def test_no_degenerate_polygons():
    """The reference draft's tail tip was a quad with a duplicated vertex. It
    rendered fine and read as a copy-paste error."""
    for group in ("ring", "tail"):
        for pts in _polys(group):
            verts = pts.split()
            assert len(verts) == len(set(verts)), f"duplicated vertex in {group}: {pts}"


def test_brand_tokens_have_not_drifted_from_the_mark():
    """The mark uses literal hex, because it is also served standalone as a
    favicon where CSS custom properties have nothing to resolve against.

    Two of those literals are tokens. If someone retunes --accent-gold in the
    template and not the mark, the tail stops resolving to the same gold the
    UI calls 'resolution' — a drift no other test would catch."""
    css = config.APP_TEMPLATE.read_text(encoding="utf-8")
    mark = logo.MARK_PATH.read_text(encoding="utf-8")

    for token, why in [
        ("--accent-gold", "the tail's resolve"),
        ("--text-primary", "the centre point"),
    ]:
        value = re.search(rf"{token}\s*:\s*(#[0-9a-fA-F]{{6}})", css).group(1)
        assert value.lower() in mark.lower(), (
            f"{token} is {value} in the template but the mark does not use it "
            f"({why}). Update web/assets/logo-mark.svg, or the mark and the UI "
            f"disagree about the brand."
        )


def test_size_below_minimum_refuses_rather_than_smudging():
    """§2 requires a simplified glyph below 24px. It doesn't exist yet (#28), so
    fail loudly instead of shipping an 11-facet ring at favicon scale."""
    with pytest.raises(NotImplementedError, match="#28"):
        logo.mark_svg(size=16)


def test_size_sets_dimensions():
    assert 'width="30"' in logo.mark_svg(size=30)
    assert 'height="30"' in logo.mark_svg(size=30)


def test_decorative_mark_is_hidden_from_screen_readers():
    """In the lockup the mark sits beside the word 'PMQs'. Announcing both
    would say the name twice."""
    assert 'aria-hidden="true"' in logo.mark_svg(title=None)
    assert 'role="img"' in logo.mark_svg(title="PMQs")


def test_lockup_wordmark_is_real_text_not_baked_into_the_svg():
    """§2's reference lockup hardcoded <text> with no font-family, so it
    rendered in the SVG user-agent default and ignored §4 entirely."""
    html = logo.lockup_html()
    assert '<div class="logo">PMQs</div>' in html
    assert "<text" not in html


def test_mark_reaches_a_rendered_page():
    html = render_inbox([])
    assert 'id="ring"' in html
    assert logo._LOGO_MARK_SENTINEL not in html if hasattr(logo, "_LOGO_MARK_SENTINEL") else True


def test_mark_is_spliced_not_duplicated():
    """One source. If the mark ever appears twice on a page, something has
    started copy-pasting it."""
    html = render_inbox([])
    assert html.count('id="ring"') == 1
