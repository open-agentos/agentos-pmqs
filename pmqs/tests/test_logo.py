"""Tests for the logo socket (web/logo.py + web/assets/*.svg).

Brand doc section 2 is still open — the per-facet bevel is coming. These pin the
things that must survive a re-cut, and deliberately do NOT pin facet
coordinates, which the design agent is expected to change.
"""

import io
import re
from xml.etree import ElementTree

import pytest

from pmqs import config
from pmqs.web import logo
from pmqs.web.render import render_inbox


def _polys(group_id: str) -> list[str]:
    svg = logo.MARK_PATH.read_text(encoding="utf-8")
    body = svg.split(f'id="{group_id}"', 1)[1].split("</g>", 1)[0]
    return re.findall(r'points="([^"]+)"', body)


# --- geometry that must survive a re-cut -----------------------------------


def test_mark_has_tight_square_viewbox():
    """The reference draft used viewBox 0 0 680 520 for artwork occupying ~18%
    of it — small and off-centre in any fixed box."""
    vb = re.search(r'viewBox="([^"]+)"', logo.logo_svg()).group(1)
    _, _, w, h = (float(v) for v in vb.split())
    assert w == h == 252.0


def test_both_variants_share_a_viewbox():
    """They must be drop-in swappable, or the threshold switch would jump."""
    def vb(svg):
        return re.search(r'viewBox="([^"]+)"', svg).group(1)
    assert vb(logo._detailed_source()) == vb(logo._fallback_source())


def test_tail_has_exactly_eight_facets():
    """One per analytical lens: eight perspectives narrowing to one point of
    resolution. If a re-cut changes this, it should be deliberate."""
    assert len(_polys("tail")) == 8


def test_ring_has_eleven_facets():
    assert len(_polys("ring")) == 11


def test_no_degenerate_polygons():
    """The reference draft's tail tip was a quad with a duplicated vertex."""
    for group in ("ring", "tail"):
        for pts in _polys(group):
            verts = pts.split()
            assert len(verts) == len(set(verts)), f"duplicated vertex in {group}: {pts}"


def test_both_variants_are_well_formed_xml():
    """The mark's comments once contained `--`, from CSS token names, which is
    illegal inside an XML comment. It went unnoticed because everything served
    goes through _strip(); only serving a raw file as a favicon exposed it."""
    for path in (logo.MARK_PATH, logo.FALLBACK_PATH):
        ElementTree.parse(path)


# --- the brand contract ----------------------------------------------------


def test_brand_tokens_have_not_drifted_from_the_mark():
    """The mark uses literal hex because it is also served standalone as a
    favicon, where custom properties have no document to resolve against.

    Two of those literals are tokens. Retune --accent-gold without touching the
    mark and the tail stops resolving to the gold the UI calls 'resolution' —
    drift nothing else would catch."""
    css = config.APP_TEMPLATE.read_text(encoding="utf-8")
    mark = logo.MARK_PATH.read_text(encoding="utf-8")

    for token, why in [("--accent-gold", "the tail's resolve"),
                       ("--text-primary", "the centre point")]:
        value = re.search(rf"{token}\s*:\s*(#[0-9a-fA-F]{{6}})", css).group(1)
        assert value.lower() in mark.lower(), (
            f"{token} is {value} in the template but the mark does not use it "
            f"({why}). Update web/assets/logo-mark.svg."
        )


def test_design_agent_comments_do_not_ship():
    assert "DESIGN AGENT" in logo.MARK_PATH.read_text(encoding="utf-8")
    assert "DESIGN AGENT" not in logo.logo_svg()
    assert "<!--" not in logo.logo_svg()


# --- the threshold ---------------------------------------------------------


def test_small_sizes_get_the_fallback_automatically():
    """Enforced in the helper, not left to call sites."""
    assert 'id="ring"' not in logo.logo_svg(16)
    assert 'id="ring"' in logo.logo_svg(128)


def test_rail_uses_the_fallback_deliberately():
    """The rail draws at 30px, below MIN_DETAIL_PX. Not an oversight: the
    detailed mark shows 0.55px² of gold at 30px, i.e. a teal ring with a teal
    tail and no resolution at all."""
    assert logo.RAIL_MARK_PX < logo.MIN_DETAIL_PX
    assert 'id="ring"' not in logo.lockup_html()


def test_size_sets_dimensions():
    assert 'width="128"' in logo.logo_svg(128)
    assert 'height="128"' in logo.logo_svg(128)


def test_fallback_keeps_the_resolve_visible_at_favicon_scale():
    """The whole reason the fallback exists. Section 2's idea is 'clarity
    arriving late, and only once earned' — if gold is sub-pixel, the mark cannot
    say it. cairosvg is a dev-time measurement tool, not a runtime dependency."""
    cairosvg = pytest.importorskip("cairosvg")
    PIL = pytest.importorskip("PIL.Image")

    def gold_px(svg, px):
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=px,
                               output_height=px, background_color="#12181c")
        im = PIL.open(io.BytesIO(png)).convert("RGB")
        return sum(1 for x in range(px) for y in range(px)
                   if (lambda c: c[0] - c[2] > 40 and c[0] > 90)(im.getpixel((x, y))))

    assert gold_px(logo.favicon_svg(), 16) >= 3, "fallback must show its resolve at 16px"
    assert gold_px(logo._detailed_source(), 16) == 0, (
        "if the detailed mark now shows gold at 16px the taper was re-cut — "
        "lower MIN_DETAIL_PX"
    )


# --- accessibility + wiring ------------------------------------------------


def test_decorative_mark_is_hidden_from_screen_readers():
    """In the lockup the mark sits beside the word 'PMQs'. Announcing both
    would say the name twice."""
    assert 'aria-hidden="true"' in logo.logo_svg(title=None)
    assert 'role="img"' in logo.logo_svg(title="PMQs")


def test_lockup_wordmark_is_real_text_not_baked_into_the_svg():
    html = logo.lockup_html()
    assert '<div class="logo">PMQs</div>' in html
    assert "<text" not in html


def test_mark_reaches_a_rendered_page_exactly_once():
    """One source. If the lockup ever appears twice, something started
    copy-pasting it. Counts the markup, not the CSS rule of the same name."""
    html = render_inbox([])
    assert "<!-- LOGO MARK -->" not in html
    assert html.count('<div class="logo-lockup">') == 1
    assert html.count("<svg") == html.count("</svg>")


def test_favicon_is_served_and_carries_no_design_brief():
    from fastapi.testclient import TestClient

    from pmqs.api.app import app

    r = TestClient(app).get("/favicon.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "DESIGN AGENT" not in r.text
    assert "<!--" not in r.text


def test_every_page_links_the_favicon():
    """render_settings() and render_error() build their own documents, so they
    each need the link — a mistake that only shows up on those two pages."""
    assert 'rel="icon"' in render_inbox([])
    from pmqs.web.render import render_error
    assert 'rel="icon"' in render_error("nope", 404)
