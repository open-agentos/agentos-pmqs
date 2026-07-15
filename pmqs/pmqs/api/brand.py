"""Brand asset routes.

Only the favicon for now. Deliberately not a StaticFiles mount: there is exactly
one asset to serve, it is generated from web/logo.py's single source, and a mount
would expose the whole assets/ directory — including logo-mark.svg, which carries
the design brief in its comments.

Fonts do not need this. They come from Google Fonts via the template's @import,
which is why the asset-serving work turned out much smaller than #28 assumed.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from pmqs.web import logo

router = APIRouter()

# A day. The mark is not final — brand doc section 2 is still open — so this is
# deliberately not immutable/1-year.
_CACHE = "public, max-age=86400"


@router.get("/favicon.svg", include_in_schema=False)
async def favicon_svg() -> Response:
    """SVG favicon.

    SVG-only, no .ico or .png fallback: every browser in current support has
    handled SVG favicons for years, and a rasterised copy would be a second
    source of truth for the mark that could silently drift from the first.
    """
    return Response(
        content=logo.favicon_svg(),
        media_type="image/svg+xml",
        headers={"Cache-Control": _CACHE},
    )
