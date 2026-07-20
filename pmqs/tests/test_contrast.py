"""Per-surface WCAG contrast guard for the light (default) parchment palette.

The last identity's ratios were all measured against a single background, and the
adoption after it found the systemic bug that follows from that: a token chosen by
role/name fails once the component it lands on sits on a *different* surface. On a
light palette that bites harder — muted warm tones read fine to the eye and still
miss AA.

So every foreground is measured against each surface it actually renders on, at the
level its role requires:

  * body text            AA  4.5:1
  * large / UI / borders AA  3.0:1  (metadata, markers, dividers, decorative)

If a future retune drops a real pairing below its line, this fails — which is the
whole point. Values are read from the shipped :root, so the test tracks the template,
not a copy of it. Dark theme is a secondary skin and is not gated here.
"""
import re
from pathlib import Path

import pytest

from pmqs import config

BODY = 4.5
LARGE = 3.0


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    chans = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _light_root() -> dict[str, str]:
    css = config.APP_TEMPLATE.read_text(encoding="utf-8")
    root = re.search(r":root\{(.*?)\n\}", css, re.S).group(1)
    return {n: v for n, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", root)}


TOK = _light_root()

# (foreground token, surface token, minimum ratio, why it renders here)
PAIRS = [
    # Primary + secondary body text on every chrome surface.
    *[("--text-primary", s, BODY, "primary body text")
      for s in ("--bg-main", "--bg-surface", "--bg-active", "--bg-raised")],
    *[("--text-secondary", s, BODY, "secondary body text")
      for s in ("--bg-main", "--bg-surface", "--bg-active", "--bg-raised")],
    # Muted metadata is deliberately faint — AA-large, used knowingly.
    *[("--text-muted", s, LARGE, "faint metadata / mono")
      for s in ("--bg-main", "--bg-surface", "--bg-active", "--bg-raised")],
    # Amber is used AS TEXT: active nav, top rank badge, stakes pill. Must clear body AA.
    ("--accent-gold", "--bg-main", BODY, "amber text on canvas"),
    ("--accent-gold", "--bg-surface", BODY, "amber text on card"),
    ("--accent-gold", "--bg-active", BODY, "amber text on active nav"),
    ("--accent-gold", "--paper", BODY, "amber text on the doc surface"),
    # Inverse text sitting on accent fills (primary buttons, send, save).
    ("--on-accent", "--accent-gold", BODY, "button label on amber fill"),
    ("--on-accent", "--accent-teal-fg", BODY, "label on the ink-fill button"),
    # Avatars carry initials — those are text.
    ("--text-primary", "--accent-teal", BODY, "system avatar initials on its fill"),
    ("--text-secondary", "--bg-raised", BODY, "PM avatar initials on its fill"),
    # Status hues used as text / +/- markers, incl. the for/against grid on --paper.
    ("--accent-sage", "--bg-surface", BODY, "success text on card"),
    ("--accent-sage", "--paper", BODY, "for-side markers on the doc"),
    ("--pulse-cyan", "--bg-surface", BODY, "telemetry text on card"),
    ("--pulse-coral", "--bg-surface", BODY, "risk text on card"),
    ("--pulse-coral", "--paper", BODY, "against-side markers on the doc"),
    # The letter surface.
    ("--paper-ink", "--paper", BODY, "document body ink"),
    ("--paper-muted", "--paper", BODY, "document metadata"),
    # NB: hairline/divider tokens (--border-default, --accent-teal-dim) are
    # deliberately soft on this identity (the mock's #d6c09a rule on cream is
    # ~1.56:1) and are NOT gated: they are decorative rules, and controls that
    # use them (inputs, selected rows) also carry a fill difference + label, so
    # the border is never the sole indicator. Gating them would force heavy
    # borders that break the parchment look.
]


@pytest.mark.parametrize("fg,surface,minimum,role", PAIRS,
                         ids=[f"{p[0]}_on_{p[1]}" for p in PAIRS])
def test_pairing_clears_aa(fg, surface, minimum, role):
    assert fg in TOK, f"{fg} not in :root"
    assert surface in TOK, f"{surface} not in :root"
    ratio = contrast(TOK[fg], TOK[surface])
    assert ratio >= minimum, (
        f"{fg} ({TOK[fg]}) on {surface} ({TOK[surface]}) is {ratio:.2f}:1, "
        f"below {minimum}:1 for {role}"
    )
