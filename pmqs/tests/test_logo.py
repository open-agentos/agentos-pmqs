"""Tests for the logo socket (web/logo.py + web/assets/*.svg).

The mark is the quill/A (brand doc section 2), a first pass to be revisited.
These pin what must survive an edit — square + shared viewBox, well-formed XML,
the two brand-token colours, the size threshold — and deliberately do NOT pin
path coordinates, which the design agent is expected to change.
"""

import re
from xml.etree import ElementTree

import pytest

from pmqs import config
from pmqs.web import logo
from pmqs.web.render import render_inbox


# --- geometry that must survive a re-cut -----------------------------------


def test_mark_has_a_square_viewbox():
    """A tile mark has to sit in a square box or it distorts at every size."""
    vb = re.search(r'viewBox="([^"]+)"', logo.logo_svg()).group(1)
    _, _, w, h = (float(v) for v in vb.split())
    assert w == h


def test_both_variants_share_a_viewbox():
    """They must be drop-in swappable, or the threshold switch would jump."""
    def vb(svg):
        return re.search(r'viewBox="([^"]+)"', svg).group(1)
    assert vb(logo._detailed_source()) == vb(logo._fallback_source())


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

    for token, why in [("--accent-gold", "the tile"),
                       ("--on-accent", "the glyph")]:
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
    assert 'id="apex"' not in logo.logo_svg(16)
    assert 'id="apex"' in logo.logo_svg(128)


def test_rail_uses_the_fallback_deliberately():
    """The rail draws at 30px, below MIN_DETAIL_PX, so it gets the sturdier
    simplified glyph (heavier strokes, no apex point) that holds up small."""
    assert logo.RAIL_MARK_PX < logo.MIN_DETAIL_PX
    assert 'id="apex"' not in logo.lockup_html()


def test_size_sets_dimensions():
    assert 'width="128"' in logo.logo_svg(128)
    assert 'height="128"' in logo.logo_svg(128)


def test_both_variants_carry_the_glyph_not_just_the_tile():
    """A tile with no A is not the mark. Both variants must draw the quill/A
    strokes, not merely the amber square."""
    for src in (logo._detailed_source(), logo._fallback_source()):
        assert src.count("<path") >= 2, "the A + crossbar strokes must be present"


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
