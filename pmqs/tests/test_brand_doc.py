"""The brand doc is the design agent's source of truth. If it describes a palette
the product doesn't ship, it is worse than no doc — it is a confident wrong answer.

This drifted once already: sections 3 and 4 both specified things the built product
didn't have, and the token migration added five tokens the doc never mentioned.
"""

import re
from pathlib import Path

import pytest

from pmqs import config

DOC = Path(__file__).resolve().parents[2] / "docs" / "brand-design-system.md"


def _shipped_tokens() -> dict[str, str]:
    css = config.APP_TEMPLATE.read_text(encoding="utf-8")
    root = re.search(r":root\{(.*?)\n\}", css, re.S).group(1)
    return {
        n: v.strip().split("/*")[0].strip()
        for n, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", root)
    }


def _doc_section(heading: str, next_heading: str) -> str:
    s = DOC.read_text(encoding="utf-8")
    return s[s.index(heading):s.index(next_heading)]


def test_doc_exists():
    assert DOC.exists(), "the brand doc is referenced by logo.py, render.py and AGENTS.md"


@pytest.mark.parametrize("token", sorted(t for t in _shipped_tokens() if not t.startswith("--font")))
def test_every_shipped_colour_token_is_documented(token):
    """Section 3 must name every colour token the template defines."""
    sec = _doc_section("## 3. Colour Tokens", "## 4. Typography")
    assert token in sec, (
        f"{token} ships in the template but section 3 of the brand doc doesn't "
        f"mention it. The doc is the design agent's source of truth; an "
        f"undocumented token is one they'll either misuse or reinvent."
    )


@pytest.mark.parametrize("token", sorted(t for t in _shipped_tokens() if not t.startswith("--font")))
def test_documented_values_match_what_ships(token):
    """Naming the token isn't enough — the value has to be right too."""
    sec = _doc_section("## 3. Colour Tokens", "## 4. Typography")
    shipped = _shipped_tokens()[token]
    m = re.search(rf"{re.escape(token)}\s*:\s*(#[0-9a-fA-F]{{6}})", sec)
    assert m, f"{token} appears in section 3 but not as a value in its :root block"
    assert m.group(1).lower() == shipped.lower(), (
        f"{token} is {shipped} in the template but {m.group(1)} in the brand doc"
    )


def test_every_shipped_font_token_is_documented():
    sec = _doc_section("## 4. Typography", "## 5. Iconography")
    for token in (t for t in _shipped_tokens() if t.startswith("--font")):
        assert token in sec, f"{token} ships but section 4 doesn't mention it"


def test_doc_does_not_still_specify_the_unlicensed_face():
    """Aeonik is a licensed CoType face PMQs doesn't hold. It may only appear as
    the substitution's rationale, never as a stack."""
    s = DOC.read_text(encoding="utf-8")
    assert not re.search(r"font-family:[^;\n]*Aeonik", s)
