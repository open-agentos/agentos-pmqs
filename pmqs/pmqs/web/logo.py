"""logo.py — the single source for the PMQs mark.

Every appearance of the mark routes through here. Nothing copy-pastes the SVG:
that is how a mark quietly drifts out of sync with itself.

Two variants, and choosing between them is NOT a judgement call at the call
site — logo_svg() picks by size. See MIN_DETAIL_PX for why the threshold sits
where it does; it is measured, not inherited from the spec.

  assets/logo-mark.svg      the detailed mark: 11 ring facets, 8 tail facets
  assets/logo-fallback.svg  the simplified glyph: solid C-ring, two-tone tail

Both share a viewBox, so they are drop-in swappable. Brand doc section 2 is
still open — the per-facet embedded bevel is the priority refinement and is in
neither file. When it lands, the design agent edits one .svg and every surface
follows.

Surfaces that need the mark:
  - the left rail lockup, spliced into templates/app.html by render.py
  - the favicon, served by api/brand.py

render_settings() and render_error() build their own standalone documents, which
is exactly why one source matters.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
MARK_PATH = _ASSETS / "logo-mark.svg"
FALLBACK_PATH = _ASSETS / "logo-fallback.svg"

#: Below this, logo_svg() returns the simplified glyph.
#:
#: Brand doc section 2 estimated 24px, on the theory that facet detail stops
#: resolving. Measured, that is wrong in both directions. The facets survive
#: fine — all three ring tones are still distinguishable at 12px. What dies is
#: the *resolve*: the tail's gold tip is 0.017% of the mark's area, and
#: rasterised against the app background, gold runs 1:740 against teal. Pixels
#: of gold, by render size:
#:
#:     16px -> 0.16   30px -> 0.55   48px -> 1.40   64px -> 2.48   128px -> ~11
#:
#: So the mark shows no resolution at all until roughly 128px — and the rail
#: draws it at 30px. 64 is where the detailed mark starts to have anything to
#: say that the fallback does not say better. Below it the fallback is not a
#: degraded substitute; it is the more faithful one.
#:
#: The real fix is the taper geometry, which is the design agent's call: section
#: 2 wants gold in "the final one or two facets" while the taper accelerates
#: toward the tip, so the facets carrying the meaning are by construction the
#: smallest. If the mark is re-cut so the resolve survives at ~30px, lower this.
MIN_DETAIL_PX = 64

#: The rail lockup. Below MIN_DETAIL_PX, so it gets the fallback — deliberately.
RAIL_MARK_PX = 30

#: The favicon. Firmly fallback territory.
FAVICON_PX = 32


def _strip(svg: str) -> str:
    """Drop the XML prolog and the design-agent brief. Those comments are for
    whoever edits the file, not for every visitor on every page."""
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r"<!--.*?-->\s*", "", svg, flags=re.DOTALL)
    return svg.strip()


@functools.lru_cache(maxsize=None)
def _detailed_source() -> str:
    return _strip(MARK_PATH.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _fallback_source() -> str:
    return _strip(FALLBACK_PATH.read_text(encoding="utf-8"))


def logo_svg(size: int | None = None, *, title: str | None = "PMQs") -> str:
    """The mark as an inline-able <svg> string, in whichever variant that size
    can actually carry.

    size:  pixel width/height. Both variants are square, so one number is
           enough. None means "leave it to CSS" and returns the detailed mark —
           pass a size if you want the threshold applied, which you almost
           always do.
    title: accessible name. Pass None where the mark is decorative and sits
           beside a real text wordmark, or screen readers announce it twice.
    """
    use_fallback = size is not None and size < MIN_DETAIL_PX
    svg = _fallback_source() if use_fallback else _detailed_source()

    if size is not None:
        svg = svg.replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
    if title:
        svg = svg.replace("<svg ", f'<svg role="img" aria-label="{title}" ', 1)
    else:
        svg = svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)
    return svg


def favicon_svg() -> str:
    """The favicon. Always the fallback: a browser tab is 16-32px.

    No width/height — a favicon should scale to whatever the browser asks for,
    and the viewBox carries the aspect. Colours in the source are literal hex
    rather than var(), because a favicon has no document whose custom properties
    it could resolve against.
    """
    return _fallback_source()


def lockup_html() -> str:
    """Mark + wordmark + tagline, for the left rail.

    The wordmark is real HTML text in the display face, not paths and not <text>
    baked into the SVG. Section 2's reference lockup hardcoded its own text with
    no font-family, so it rendered in the SVG user-agent default and ignored the
    type system entirely. As markup it inherits the type stack, scales with it,
    and stays selectable.

    The mark is aria-hidden here: "PMQs" is right beside it as text.
    """
    return (
        '<div class="logo-lockup">'
        f"{logo_svg(RAIL_MARK_PX, title=None)}"
        '<div class="logo-text">'
        '<div class="logo">PMQs</div>'
        '<div class="logo-sub">acme-app · production</div>'
        "</div>"
        "</div>"
    )


# Deprecated alias — #27 shipped this name before the fallback existed.
mark_svg = logo_svg
