"""render.py — template real Questions into the mockup's Inbox .card markup.

Phase 0 render task: reuse pmqs-mockup.html's existing structure/CSS/JS verbatim,
replacing ONLY the hardcoded Inbox fixture cards with generated cards from real data.
Workspace/Outcomes views stay exactly as-is/static (per spec).

Approach: read the mockup once, splice generated card HTML into the Inbox region
between the quick-add block and the close of .inbox-wrap. Everything else is untouched.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from pmqs import config

# Region: from end of the quick-add block to the close of .inbox-wrap.
# The mockup has <div class="quick-add">...</div> then fixture cards then </div></div>.
_QUICK_ADD_RE = re.compile(
    r'(<div class="quick-add">.*?</div>\s*</div>)',  # quick-add wrapper (input+button, then its close)
    re.DOTALL,
)
# Fallback: everything between quick-add close and the inbox-wrap close.
_CARDS_REGION_RE = re.compile(
    r'(<div class="quick-add">.*?</div>\s*)(.*?)(\s*</div>\s*</div>\s*<!-- WORKSPACE VIEW -->)',
    re.DOTALL,
)


def _pill(text: str, cls: str = "") -> str:
    c = f"pill {cls}".strip()
    return f'<span class="{c}">{html.escape(text)}</span>'


def question_card_html(q: Any) -> str:
    """Render one Question into the mockup's .card markup."""
    source = getattr(q, "source", "system")
    status = getattr(q, "status", "proposed")
    lens_tags = getattr(q, "lens_tags_list", None)
    if lens_tags is None:
        lens_tags = getattr(q, "lens_tags", []) or []
    score = getattr(q, "score", None)

    # Card variant class mirrors mockup: system | asked | saved.
    if status == "saved":
        variant = "saved"
    elif source == "pm":
        variant = "asked"
    else:
        variant = "system"

    pills = []
    for t in lens_tags:
        pills.append(_pill(t.replace("_", " ")))
    pills.append(_pill("Asked by you" if source == "pm" else "Raised by system", "source"))
    if score is not None:
        pills.append(_pill(f"score {score:.2f}"))

    title = html.escape(getattr(q, "title", "") or "")
    ev = getattr(q, "evidence_list", None)
    if ev is None:
        ev = getattr(q, "evidence", []) or []
    ref = ""
    if ev:
        ref = html.escape(str(ev[0].get("ref", "")))
    age_span = f'<span class="card-age">{ref}</span>' if ref else ""

    saved_style = ' style="margin-top:22px;"' if variant == "saved" else ""
    return f"""        <div class="card {variant}"{saved_style}>
          <div class="card-main">
            <div class="card-title">{title}</div>
            <div class="card-meta">
              {' '.join(pills)}
              {age_span}
            </div>
          </div>
          <div class="card-actions">
            <div class="icon-btn primary" title="War-room">⚔</div>
            <div class="icon-btn" title="Save for later">⏱</div>
            <div class="icon-btn" title="Dismiss">✕</div>
          </div>
        </div>"""


def render_inbox(questions: list[Any], mockup_path: Path | None = None) -> str:
    """Return the full mockup HTML with Inbox fixture cards replaced by real ones."""
    path = mockup_path or config.MOCKUP_HTML
    src = Path(path).read_text(encoding="utf-8")

    if questions:
        cards_html = "\n\n".join(question_card_html(q) for q in questions)
    else:
        cards_html = (
            '        <div class="card system"><div class="card-main">'
            '<div class="card-title">No questions yet — triggers have not produced any, '
            'and none were added.</div></div></div>'
        )

    def _replace(m: re.Match) -> str:
        return f"{m.group(1)}\n\n{cards_html}\n{m.group(3)}"

    new_src, n = _CARDS_REGION_RE.subn(_replace, src)
    if n == 0:
        # Structure changed; degrade gracefully rather than 500.
        raise RuntimeError("Could not locate Inbox card region in mockup HTML")
    return new_src


def render_settings(db: Any) -> str:
    """Render a minimal Settings page (LLM section). Reuses mockup CSS via a <link>-free
    inline style pull is overkill for the prototype — a plain, self-contained page that
    matches the dark theme is enough. The API key is NEVER echoed: shown masked.
    """
    from pmqs import settings as settings_mod

    cfg = settings_mod.get_llm(db)
    has_raw = bool(cfg.get("api_key_raw"))
    key_display = "•••••••• (stored)" if has_raw else html.escape(cfg.get("api_key_ref") or "")
    provider = html.escape(cfg.get("provider", ""))
    model = html.escape(cfg.get("model", ""))
    base_url = html.escape(cfg.get("base_url", ""))

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>PMQs — Settings</title>
<style>
body{{background:#1a1a1f;color:#e8e6e0;font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:40px}}
.wrap{{max-width:560px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8a8780;font-size:12.5px;margin-bottom:28px}}
.section{{background:#232329;border:1px solid #34343c;border-radius:10px;padding:22px;margin-bottom:18px}}
.section h2{{font-size:14px;margin:0 0 16px;color:#c9c6be}}
label{{display:block;font-size:12px;color:#8a8780;margin:12px 0 4px}}
input{{width:100%;box-sizing:border-box;background:#1a1a1f;border:1px solid #3a3a44;color:#e8e6e0;
border-radius:6px;padding:8px 10px;font-size:13px}}
.hint{{font-size:11px;color:#6a675f;margin-top:4px}}
button{{margin-top:18px;background:#4a7d6e;color:#fff;border:0;border-radius:6px;padding:9px 18px;
font-size:13px;cursor:pointer}} a{{color:#7fb8a6}}
</style></head><body><div class="wrap">
<h1>Settings</h1><div class="sub">PMQs prototype configuration · <a href="/">← Inbox</a></div>
<form method="post" action="/settings">
<div class="section"><h2>LLM provider</h2>
<label>Provider</label><input name="provider" value="{provider}" placeholder="anthropic">
<label>Model</label><input name="model" value="{model}" placeholder="anthropic/claude-haiku-4-5-20251001">
<label>API key env var (recommended)</label><input name="api_key_ref" value="{key_display}" placeholder="ANTHROPIC_API_KEY">
<div class="hint">Reference an environment variable rather than pasting a key. The key is never displayed once stored.</div>
<label>API key (optional, inline — stored, never shown)</label><input name="api_key_raw" type="password" value="" placeholder="leave blank to keep current">
<label>Base URL (optional, for OpenAI-compatible endpoints)</label><input name="base_url" value="{base_url}" placeholder="">
<button type="submit">Save</button>
</div></form></div></body></html>"""
