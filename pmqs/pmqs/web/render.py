"""render.py — template real data into the mockup's existing markup.

Reuse pmqs-mockup.html's structure/CSS/JS verbatim, replacing only the hardcoded
fixture content with real data via anchored regex splices. Phase 0 wired the Inbox;
Phase 2 wires the Workspace. Everything not spliced is left untouched.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from pmqs import config

# --- Inbox (Phase 0): region from quick-add close to the inbox-wrap close. ---
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
    ref = html.escape(str(ev[0].get("ref", ""))) if ev else ""
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
        raise RuntimeError("Could not locate Inbox card region in mockup HTML")
    return new_src


# ---------------------------------------------------------------- Workspace (Phase 2)
# Anchored splices into the existing Workspace markup. Each captures (open)(inner)(close);
# we replace the inner with real data, leaving all CSS/JS/structure intact.
_WS_TITLE_RE = re.compile(r'(<span class="ws-title">)(.*?)(</span>)', re.DOTALL)
_CONVO_RE = re.compile(
    r'(<div class="convo-scroll"[^>]*>)(.*?)(</div>\s*<div class="convo-input">)', re.DOTALL
)
_TAB_DOC_RE = re.compile(r'(<div id="tab-doc">)(.*?)(</div>\s*<div id="tab-chart")', re.DOTALL)
_TAB_EVID_RE = re.compile(
    r'(<div id="tab-evidence"[^>]*>)(.*?)(</div>\s*<div id="tab-proposed")', re.DOTALL
)
_TAB_PROP_RE = re.compile(
    r'(<div id="tab-proposed"[^>]*>)(.*?)(</div>\s*</div>\s*</div>\s*</div>)', re.DOTALL
)
_STATS_RE = re.compile(r'(<span class="session-stats">).*?(</span>)', re.DOTALL)


def _msg_html(m: Any) -> str:
    role = getattr(m, "role", "system")
    cls = "pm" if role == "pm" else "system"
    label = "You" if role == "pm" else ("System" if role == "system" else "War-room")
    bubble = "pm-bubble" if role == "pm" else "sys-bubble"
    return (
        f'<div class="msg {cls}"><div class="msg-label">{label}</div>'
        f'<div class="msg-body {bubble}">{html.escape(getattr(m, "content", ""))}</div></div>'
    )


def _evidence_html(evidence: list[dict]) -> str:
    if not evidence:
        return '<div class="evidence-item"><div class="evidence-title">No evidence bound yet.</div></div>'
    out = []
    for e in evidence:
        title = html.escape(f"{e.get('type', 'ref')} {e.get('ref', '')}".strip())
        url = html.escape(e.get("url", ""))
        out.append(
            f'<div class="evidence-item"><div class="evidence-title">{title}</div>'
            f'<div class="evidence-sub">{url}</div></div>'
        )
    return "\n".join(out)


def _proposed_html(proposed: list[Any]) -> str:
    if not proposed:
        return (
            '<div class="proposed-item"><div class="proposed-title">'
            'No proposed questions yet — click "Run lenses" to generate them.</div></div>'
        )
    out = []
    for q in proposed:
        title = html.escape(getattr(q, "title", ""))
        out.append(
            f'<div class="proposed-item"><div class="proposed-title">{title}</div>'
            f'<div class="proposed-actions">'
            f'<button class="p-add" onclick="acceptProposed(this)">+ Add to inbox</button>'
            f"<button class=\"p-dismiss\" onclick=\"this.closest('.proposed-item').remove()\">Dismiss</button>"
            f"</div></div>"
        )
    return "\n".join(out)


def _position_doc_html(doc: dict | None) -> str:
    if not doc:
        return (
            '<div class="doc"><h3>Position document</h3>'
            '<div class="doc-sub">Not generated yet — generate on demand.</div></div>'
        )

    def sec(label: str, key: str) -> str:
        val = html.escape(str(doc.get(key, "")))
        return f'<div class="doc-section"><div class="doc-label">{label}</div><div class="doc-text">{val}</div></div>'

    return (
        '<div class="doc"><h3>Position document</h3>'
        '<div class="doc-sub">Voter-Guide format · generated on demand</div>'
        + sec("Summary", "summary")
        + sec("What your decision means", "what_your_vote_means")
        + sec("Background &amp; impact", "background_impact")
        + '<div class="doc-section doc-grid">'
        + '<div class="doc-box for"><div class="doc-label">Argument for</div>'
        + f'<div class="doc-text">{html.escape(str(doc.get("argument_for", "")))}</div>'
        + '<div class="doc-label">Rebuttal</div>'
        + f'<div class="doc-text">{html.escape(str(doc.get("rebuttal_for", "")))}</div></div>'
        + '<div class="doc-box against"><div class="doc-label">Argument against</div>'
        + f'<div class="doc-text">{html.escape(str(doc.get("argument_against", "")))}</div>'
        + '<div class="doc-label">Rebuttal</div>'
        + f'<div class="doc-text">{html.escape(str(doc.get("rebuttal_against", "")))}</div></div>'
        + "</div></div>"
    )


def _splice3(regex: re.Pattern, replacement: str, s: str, what: str) -> str:
    """Replace the middle group of a 3-group (open)(inner)(close) regex."""
    new, n = regex.subn(lambda m: f"{m.group(1)}{replacement}{m.group(3)}", s)
    if n == 0:
        raise RuntimeError(f"Could not locate Workspace region: {what}")
    return new


def render_workspace(
    session: Any,
    messages: list[Any],
    evidence: list[dict],
    proposed: list[Any],
    position_doc: dict | None,
    mockup_path: Path | None = None,
) -> str:
    """Splice real war-room session data into the mockup's Workspace view.

    Preserves all CSS/JS and the Inbox/Outcomes views. Replaces: ws-title, conversation
    messages, position-doc tab, evidence tab, proposed-questions tab, and session stats.
    """
    src = Path(mockup_path or config.MOCKUP_HTML).read_text(encoding="utf-8")

    title = html.escape(session.topic or "War-room session")
    convo = "\n".join(_msg_html(m) for m in messages) or (
        '<div class="msg system"><div class="msg-label">System</div>'
        '<div class="msg-body sys-bubble">Session open. Ask a question or push back below.</div></div>'
    )
    n_exchanges = sum(1 for m in messages if getattr(m, "role", "") == "pm")

    src = _splice3(_WS_TITLE_RE, title, src, "ws-title")
    src = _splice3(_CONVO_RE, convo, src, "convo-scroll")
    src = _splice3(_TAB_DOC_RE, _position_doc_html(position_doc), src, "tab-doc")
    src = _splice3(_TAB_EVID_RE, _evidence_html(evidence), src, "tab-evidence")
    src = _splice3(_TAB_PROP_RE, _proposed_html(proposed), src, "tab-proposed")

    src, n = _STATS_RE.subn(
        lambda m: f"{m.group(1)}<span>{n_exchanges}</span> exchanges{m.group(2)}", src
    )
    if n == 0:
        raise RuntimeError("Could not locate Workspace region: session-stats")
    return src


def render_settings(db: Any) -> str:
    """Render a minimal Settings page (LLM section). Self-contained dark-theme page.
    The API key is NEVER echoed back: shown masked.
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
