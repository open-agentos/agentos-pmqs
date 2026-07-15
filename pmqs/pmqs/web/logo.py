"""logo.py — the single source for the PMQs mark.

Every appearance of the mark routes through here. Nothing copy-pastes the SVG:
that is how a mark quietly drifts out of sync with itself.

The mark's geometry lives in assets/logo-mark.svg and NOT in this module, on
purpose. Brand doc §2 is still open — the per-facet embedded bevel is the
priority refinement and is not in the current draft. When that lands, the design
agent edits one .svg file and every surface picks it up. This module is the
socket; the .svg is the part that changes.

Surfaces that need the mark today:
  - the left rail lockup, spliced into templates/app.html by render.py
  - (soon, #28) the favicon, plus a simplified glyph below the minimum size

render_settings() and render_error() build their own standalone documents rather
than using the template, which is exactly why one source matters.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
MARK_PATH = _ASSETS / "logo-mark.svg"

# Brand doc §2: below this, drop the facet detail for a simplified solid glyph.
# The figure is an ESTIMATE inherited from the spec and has never been tested —
# see #28, which is meant to establish it empirically rather than trust it.
MIN_DETAIL_PX = 24


@functools.lru_cache(maxsize=None)
def _mark_source() -> str:
    """The raw mark, read once. Comments stripped — they're for the design
    agent editing the file, not for every page we serve."""
    svg = MARK_PATH.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r"<!--.*?-->\s*", "", svg, flags=re.DOTALL)
    return svg.strip()


def mark_svg(size: int | None = None, *, title: str | None = "PMQs") -> str:
    """The mark alone, as an inline-able <svg> string.

    size: pixel width/height. The mark is square (viewBox 174 134 252 252), so
          one number is enough. None leaves it to CSS.
    title: accessible name. Pass None where the mark is decorative and sits
           beside a real text wordmark — otherwise screen readers announce the
           name twice.
    """
    svg = _mark_source()

    if size is not None:
        if size < MIN_DETAIL_PX:
            # #28 will return the simplified glyph here. Until it exists, be
            # loud rather than silently shipping an 11-facet ring at 16px,
            # where it is a smudge.
            raise NotImplementedError(
                f"size {size}px is below MIN_DETAIL_PX ({MIN_DETAIL_PX}px) and the "
                "simplified fallback glyph does not exist yet — see #28. "
                "Render at >= 24px, or implement fallback_svg()."
            )
        svg = svg.replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)

    if title:
        svg = svg.replace("<svg ", '<svg role="img" aria-label="%s" ' % title, 1)
    else:
        svg = svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)

    return svg


def lockup_html() -> str:
    """Mark + wordmark + tagline, for the left rail.

    The wordmark is real HTML text in --font-display, not paths and not <text>
    baked into the SVG. Brand doc §2's reference lockup hardcoded its own text
    with no font-family, so it rendered in the SVG user-agent default and
    ignored the type system entirely. As markup it inherits §4 properly, scales
    with the type scale, stays selectable, and stays legible to screen readers.

    The mark is aria-hidden here: "PMQs" is right next to it as text.
    """
    return (
        '<div class="logo-lockup">'
        f'{mark_svg(title=None)}'
        '<div class="logo-text">'
        '<div class="logo">PMQs</div>'
        '<div class="logo-sub">acme-app · production</div>'
        "</div>"
        "</div>"
    )
