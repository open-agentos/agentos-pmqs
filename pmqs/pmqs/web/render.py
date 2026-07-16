"""render.py — splice real data into the app template's existing markup.

Reuses web/templates/app.html's structure/CSS/JS verbatim, replacing only the
hardcoded fixture content with real data via anchored regex splices. Phase 0 wired
the Inbox; Phase 2 wires the Workspace. Everything not spliced is left untouched.

IMPORTANT: the splices below anchor on the template's class names, DOM nesting and
HTML comment sentinels. Those names are a load-bearing API, not cosmetic, and no
test asserts on them — breakage surfaces at runtime, not in CI. Colours, fonts and
spacing in the template are free to change; structure and names are not.
See web/TEMPLATE-CONTRACT.md.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from pmqs import config
from pmqs.web import logo

# --- Live wiring JS: injected into rendered pages so the template's buttons call the
# real backend endpoints instead of the demo's client-side stubs. Uses classic form
# POSTs (303 redirects) to match the server routes; no fetch/JSON needed. ---
_LIVE_JS_COMMON = """
<script>
// PMQs live wiring (injected by render.py) — overrides the template's demo handlers.
function pmqsPost(action, fields){
  const f = document.createElement('form');
  f.method = 'POST'; f.action = action;
  for (const k in (fields||{})){
    const i = document.createElement('input');
    i.type = 'hidden'; i.name = k; i.value = fields[k];
    f.appendChild(i);
  }
  document.body.appendChild(f); f.submit();
}
function pmqsOpenWorkspace(qid){ pmqsPost('/workspace/open', {question_id: qid || ''}); }
function pmqsSetStatus(qid, status){ pmqsPost('/questions/'+qid+'/status', {status: status}); }
// Make the top-nav Outcomes item load the real ledger page.
document.addEventListener('DOMContentLoaded', function(){
  var nav = document.querySelector('.nav-item[data-nav="outcomes"]');
  if (nav) nav.addEventListener('click', function(e){
    e.stopImmediatePropagation();
    window.location.href = '/outcomes';
  }, true);
  var inboxNav = document.querySelector('.nav-item[data-nav="inbox"]');
  if (inboxNav) inboxNav.addEventListener('click', function(){ window.location.href = '/'; }, true);
  // Phase 4: add a Settings link to the left rail (template has no way to reach /settings).
  var rail = document.querySelector('.rail-spacer') || document.querySelector('.nav-item');
  if (rail && !document.getElementById('pmqs-settings-nav')) {
    var s = document.createElement('div');
    s.className = 'nav-item';
    s.id = 'pmqs-settings-nav';
    s.textContent = 'Settings';
    s.style.cursor = 'pointer';
    s.addEventListener('click', function(){ window.location.href = '/settings'; });
    // insert before the rail spacer if present, else after the last nav-item
    if (rail.classList && rail.classList.contains('rail-spacer')) {
      rail.parentNode.insertBefore(s, rail);
    } else {
      rail.parentNode.appendChild(s);
    }
  }
});
</script>
"""


def _inject_before_body_close(src: str, snippet: str) -> str:
    """Insert snippet just before </body>. Falls back to appending."""
    idx = src.rfind("</body>")
    if idx == -1:
        return src + snippet
    return src[:idx] + snippet + src[idx:]


def render_error(message: str, status: int = 404) -> str:
    """Minimal styled HTML error page for browser-facing routes (not /api/*)."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>PMQs — {status}</title><link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>body{{background:#1a1a1f;color:#e8e6e0;font:15px/1.6 -apple-system,system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.box{{text-align:center}} a{{color:#7fb8a6}} h1{{font-size:42px;margin:0 0 8px;color:#8a8780}}</style>
</head><body><div class="box"><h1>{status}</h1><div>{html.escape(message)}</div>
<div style="margin-top:16px"><a href="/">← Back to Inbox</a></div></div></body></html>"""

# --- Inbox (Phase 0): region from quick-add close to the inbox-wrap close. ---
# The template's placeholder for the mark. logo.py is the single source; see
# TEMPLATE-CONTRACT.md. Every render path loads through _load_template() so the
# splice happens exactly once, in one place.
_LOGO_MARK_SENTINEL = "<!-- LOGO MARK -->"


def _load_template(template_path=None) -> str:
    """Read the app template and inject the logo mark."""
    src = Path(template_path or config.APP_TEMPLATE).read_text(encoding="utf-8")
    return src.replace(_LOGO_MARK_SENTINEL, logo.mark_svg(title=None), 1)


_CARDS_REGION_RE = re.compile(
    r'(<div class="quick-add">.*?</div>\s*)(.*?)(\s*</div>\s*</div>\s*<!-- WORKSPACE VIEW -->)',
    re.DOTALL,
)


def _pill(text: str, cls: str = "") -> str:
    c = f"pill {cls}".strip()
    return f'<span class="{c}">{html.escape(text)}</span>'


def question_card_html(q: Any) -> str:
    """Render one Question into the template's .card markup."""
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
    elif source == "news":
        variant = "system news"  # reuse system card styling; 'news' hook for the pill
    else:
        variant = "system"

    pills = []
    for t in lens_tags:
        pills.append(_pill(t.replace("_", " ")))
    if source == "news":
        pills.append(_pill("From news", "source"))
    elif source == "pm":
        pills.append(_pill("Asked by you", "source"))
    else:
        pills.append(_pill("Raised by system", "source"))
    if score is not None:
        pills.append(_pill(f"score {score:.2f}"))

    title = html.escape(getattr(q, "title", "") or "")
    ev = getattr(q, "evidence_list", None)
    if ev is None:
        ev = getattr(q, "evidence", []) or []
    ref = html.escape(str(ev[0].get("ref", ""))) if ev else ""
    age_span = f'<span class="card-age">{ref}</span>' if ref else ""

    qid = html.escape(str(getattr(q, "id", "") or ""))
    saved_style = ' style="margin-top:22px;"' if variant == "saved" else ""
    # data-qid + click opens the real war-room for this question (see _LIVE_JS).
    return f"""        <div class="card {variant}"{saved_style} data-qid="{qid}" onclick="pmqsOpenWorkspace('{qid}')">
          <div class="card-main">
            <div class="card-title">{title}</div>
            <div class="card-meta">
              {' '.join(pills)}
              {age_span}
            </div>
          </div>
          <div class="card-actions" onclick="event.stopPropagation()">
            <div class="icon-btn primary" title="War-room" onclick="pmqsOpenWorkspace('{qid}')">⚔</div>
            <div class="icon-btn" title="Save for later" onclick="pmqsSetStatus('{qid}','saved')">⏱</div>
            <div class="icon-btn" title="Dismiss" onclick="pmqsSetStatus('{qid}','dismissed')">✕</div>
          </div>
        </div>"""


def render_inbox(questions: list[Any], template_path: Path | None = None,
                 flash: str | None = None, refreshed: str | None = None) -> str:
    """Return the full app HTML with Inbox fixture cards replaced by real ones.

    `flash` (optional): 'none' or an integer N — news-ingest banner.
    `refreshed` (optional): integer N — repo-refresh banner ("Pulled N from the repo").
    """
    src = _load_template(template_path)

    banner = _flash_banner(flash) + _refresh_banner(refreshed)
    if questions:
        cards_html = banner + "\n\n".join(question_card_html(q) for q in questions)
    else:
        # Explicit empty-state with an action — do NOT silently swap to a different
        # data source (that caused the home-page-changes-after-war-room bug).
        cards_html = banner + (
            '        <div class="card system"><div class="card-main">'
            '<div class="card-title">Your Inbox is empty.</div>'
            '<div class="card-meta">Pull questions from the repo, or add your own above.</div>'
            '</div>'
            '<div class="card-actions" onclick="event.stopPropagation()">'
            '<div class="icon-btn primary" title="Pull from repo" onclick="pmqsRefresh()">⟳</div>'
            '</div></div>'
        )

    def _replace(m: re.Match) -> str:
        return f"{m.group(1)}\n\n{cards_html}\n{m.group(3)}"

    new_src, n = _CARDS_REGION_RE.subn(_replace, src)
    if n == 0:
        raise RuntimeError("Could not locate Inbox card region in app template")

    # Always-visible Refresh control in the Inbox header (testing convenience): runs the
    # structural-trigger pipeline against the repo. Replaces the plain "Inbox" header.
    header_html = (
        '<div class="inbox-header" style="display:flex;align-items:center;gap:12px;'
        'justify-content:space-between;">'
        '<span>Inbox</span>'
        '<button onclick="pmqsRefresh()" title="Pull questions from the repo" '
        'style="background:#4a7d6e;color:#fff;border:0;border-radius:6px;padding:6px 14px;'
        'font-size:12.5px;cursor:pointer;">⟳ Refresh</button>'
        '</div>'
    )
    new_src, hn = re.subn(r'<div class="inbox-header">Inbox</div>', header_html, new_src)
    # (hn==0 tolerated: header markup changed; the empty-state button still works.)

    # Wire quick-add + card clicks to real endpoints (override template demo JS).
    # Also force the Inbox view active on load so no war-room/workspace header bleeds in.
    inbox_js = _LIVE_JS_COMMON + """
<script>
// Override quick-add to create a real PM question server-side.
function addQuestion(){
  var input = document.getElementById('quick-add-input');
  var val = (input && input.value || '').trim();
  if(!val) return;
  pmqsPost('/quick-add', {title: val});
}
function pmqsRefresh(){ pmqsPost('/refresh', {}); }
// The home page is always the Inbox — never leave another view active.
document.addEventListener('DOMContentLoaded', function(){
  if (typeof showView === 'function') showView('inbox');
  // H2: wire filter pills to server-side filtering (?source=).
  var map = {all: '/', asked: '/?source=pm', system: '/?source=system'};
  document.querySelectorAll('.filter-pill').forEach(function(p){
    var f = p.getAttribute('data-filter');
    if (map[f] !== undefined) {
      p.addEventListener('click', function(e){
        e.stopImmediatePropagation();
        window.location.href = map[f];
      }, true);
    }
  });
});
</script>
"""
    return _inject_before_body_close(new_src, inbox_js)


def _flash_banner(flash: str | None) -> str:
    if not flash:
        return ""
    if flash == "none":
        msg = "Nothing relevant in the news today."
    else:
        try:
            n = int(flash)
            msg = f"{n} new question{'s' if n != 1 else ''} from news."
        except ValueError:
            return ""
    return (
        f'        <div class="card system" style="border-left:3px solid #4a7d6e;">'
        f'<div class="card-main"><div class="card-title">{html.escape(msg)}</div></div></div>\n\n'
    )


def _refresh_banner(refreshed: str | None) -> str:
    if refreshed is None or refreshed == "":
        return ""
    try:
        n = int(refreshed)
    except ValueError:
        return ""
    if n == 0:
        msg = "Refreshed — no new questions from the repo (no triggers fired)."
    else:
        msg = f"Pulled {n} question{'s' if n != 1 else ''} from the repo."
    return (
        f'        <div class="card system" style="border-left:3px solid #4a7d6e;">'
        f'<div class="card-main"><div class="card-title">{html.escape(msg)}</div></div></div>\n\n'
    )


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
        if e.get("type") == "news":
            # Attributed-but-hedged news citation.
            src = html.escape(e.get("source", "") or "source")
            title = html.escape(e.get("title", "") or "")
            date = html.escape(e.get("date", "") or "")
            url = html.escape(e.get("url", "") or "")
            meta = f'{src}' + (f' · {date}' if date else '')
            link = f'<a href="{url}">{url}</a>' if url else ''
            out.append(
                f'<div class="evidence-item"><div class="evidence-title">“{title}”</div>'
                f'<div class="evidence-sub">reportedly, via {meta} {link}</div></div>'
            )
        else:
            title = html.escape(f"{e.get('type', 'ref')} {e.get('ref', '')}".strip())
            url = html.escape(e.get("url", ""))
            out.append(
                f'<div class="evidence-item"><div class="evidence-title">{title}</div>'
                f'<div class="evidence-sub">{url}</div></div>'
            )
    return "\n".join(out)


def _proposed_html(proposed: list[Any], session_id: str = "") -> str:
    run_btn = (
        f'<button class="p-add" style="margin-bottom:14px" '
        f'onclick="pmqsRunLenses()">⟳ Run lenses</button>'
    )
    if not proposed:
        return (
            run_btn
            + '<div class="proposed-item"><div class="proposed-title">'
            'No proposed questions yet — click "Run lenses" to generate them.</div></div>'
        )
    out = [run_btn]
    for q in proposed:
        title = html.escape(getattr(q, "title", ""))
        qid = html.escape(str(getattr(q, "id", "") or ""))
        out.append(
            f'<div class="proposed-item"><div class="proposed-title">{title}</div>'
            f'<div class="proposed-actions">'
            f"<button class=\"p-add\" onclick=\"pmqsAddProposed('{qid}', this)\">+ Add to inbox</button>"
            f"<button class=\"p-dismiss\" onclick=\"this.closest('.proposed-item').remove()\">Dismiss</button>"
            f"</div></div>"
        )
    return "\n".join(out)


def _position_doc_html(doc: dict | None) -> str:
    if not doc:
        return (
            '<div class="doc"><h3>Position document</h3>'
            '<div class="doc-sub">Not generated yet — generate on demand (one-time).</div>'
            '<button class="p-add" style="margin-top:12px" onclick="pmqsGenDoc()">✎ Generate position document</button>'
            '</div>'
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
    template_path: Path | None = None,
) -> str:
    """Splice real war-room session data into the template's Workspace view.

    Preserves all CSS/JS and the Inbox/Outcomes views. Replaces: ws-title, conversation
    messages, position-doc tab, evidence tab, proposed-questions tab, and session stats.
    """
    src = _load_template(template_path)

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
    src = _splice3(_TAB_PROP_RE, _proposed_html(proposed, session.id), src, "tab-proposed")

    src, n = _STATS_RE.subn(
        lambda m: f"{m.group(1)}<span>{n_exchanges}</span> exchanges{m.group(2)}", src
    )
    if n == 0:
        raise RuntimeError("Could not locate Workspace region: session-stats")

    # Inject session-aware live wiring: override the template's demo handlers so the
    # war-room buttons hit real endpoints for THIS session.
    sid = session.id
    ws_js = _LIVE_JS_COMMON + f"""
<script>
var PMQS_SID = {sid!r};
// Send a chat message to the real war-room endpoint (LLM probe reply).
function sendMsg(){{
  var input = document.getElementById('chat-input');
  var val = (input && input.value || '').trim();
  if(!val) return;
  pmqsPost('/workspace/'+PMQS_SID+'/message', {{content: val}});
}}
function pmqsRunLenses(){{ pmqsPost('/workspace/'+PMQS_SID+'/run-lenses', {{}}); }}
function pmqsGenDoc(){{ pmqsPost('/workspace/'+PMQS_SID+'/position-doc', {{}}); }}
function pmqsAddProposed(qid, btn){{ pmqsPost('/workspace/'+PMQS_SID+'/proposed/'+qid+'/add', {{}}); }}
// Outcome bar → real typed-outcome endpoint.
function addOutcome(type, label){{
  pmqsPost('/workspace/'+PMQS_SID+'/outcome', {{type: type, title: label || ''}});
}}
// Neutralize the template's client-only acceptProposed (superseded by pmqsAddProposed).
function acceptProposed(btn){{ /* handled by pmqsAddProposed */ }}
// Land on the Workspace view when arriving at this page.
document.addEventListener('DOMContentLoaded', function(){{
  if (typeof showView === 'function') showView('workspace');
}});
</script>
"""
    return _inject_before_body_close(src, ws_js)


# ---------------------------------------------------------------- Outcomes (Phase 3)
_OUTCOMES_LIST_RE = re.compile(
    r'(<div id="outcomes-list">)(.*?)(</div>\s*</div>\s*</div>\s*</div>\s*</div>)', re.DOTALL
)
_SUM_RE_TMPL = r'(<div class="summary-num" id="sum-{t}">)[^<]*(</div>)'
_LEDGER_TAG = {
    "issue": "Issue", "policy": "Policy", "document": "Document",
    "meeting": "Meeting", "question": "Question",
}


def _outcome_title(otype: str, payload: dict) -> str:
    if otype == "policy":
        return payload.get("text", "")
    return payload.get("title", "") or payload.get("text", "")


def _ledger_item_html(o: Any, payload: dict) -> str:
    otype = o.type
    tag = _LEDGER_TAG.get(otype, otype.title())
    title = html.escape(_outcome_title(otype, payload) or "(untitled)")
    src = "from war-room" + ("" if o.session_id else " · direct")
    ref = ""
    if o.github_ref:
        ref = f'<div class="ledger-src"><a href="{html.escape(o.github_ref)}">{html.escape(o.github_ref)}</a></div>'
    else:
        ref = f'<div class="ledger-src">{html.escape(src)}</div>'
    return (
        f'<div class="ledger-item" data-type="{otype}">'
        f'<span class="ledger-tag {otype}">{tag}</span>'
        f'<div class="ledger-main">{title}{ref}</div>'
        f'<span class="ledger-time"></span></div>'
    )


def render_outcomes(db: Any, template_path: Path | None = None, *, workspace_id: str | None = None) -> str:
    """Splice real outcome rows + summary counts into the template's Outcomes view.

    Mirrors the Inbox wiring: replace the static ledger fixtures and the summary-strip
    numbers with real data. Inbox/Workspace views preserved. `workspace_id` scopes the
    ledger to one product (see #56); omitted, it shows every workspace's outcomes --
    the pre-multi-product behaviour existing callers still rely on.
    """
    from pmqs import repository

    src = _load_template(template_path)
    outcomes = repository.list_outcomes(db, workspace_id=workspace_id)
    # newest first by created_at
    outcomes = sorted(outcomes, key=lambda o: getattr(o, "created_at", ""), reverse=True)

    counts = {"issue": 0, "policy": 0, "document": 0, "meeting": 0, "question": 0}
    items = []
    for o in outcomes:
        counts[o.type] = counts.get(o.type, 0) + 1
        items.append(_ledger_item_html(o, repository.outcome_payload(o)))

    if items:
        ledger_html = "\n".join(items)
    else:
        ledger_html = '<div class="ledger-item"><div class="ledger-main">No outcomes yet.</div></div>'

    new_src, n = _OUTCOMES_LIST_RE.subn(lambda m: f"{m.group(1)}{ledger_html}{m.group(3)}", src)
    if n == 0:
        raise RuntimeError("Could not locate Outcomes list region in app template")

    # Update the 5 summary-strip counts.
    for t, c in counts.items():
        new_src = re.sub(
            _SUM_RE_TMPL.format(t=t),
            lambda m, _c=c: f"{m.group(1)}{_c}{m.group(2)}",
            new_src,
        )
    outcomes_js = _LIVE_JS_COMMON + """
<script>
document.addEventListener('DOMContentLoaded', function(){
  if (typeof showView === 'function') showView('outcomes');
});
</script>
"""
    return _inject_before_body_close(new_src, outcomes_js)


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

    news = settings_mod.get_news_config(db)
    n_has_raw = bool(news.get("api_key_raw"))
    n_key_display = "•••••••• (stored)" if n_has_raw else html.escape(news.get("api_key_ref") or "")
    n_queries = html.escape("\n".join(news.get("queries", [])))
    n_profile = html.escape(news.get("product_profile", ""))
    n_top = html.escape(str(news.get("top_n", 3)))
    n_thresh = html.escape(str(news.get("min_relevance", 0.5)))

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>PMQs — Settings</title><link rel="icon" type="image/svg+xml" href="/favicon.svg">
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
textarea{{width:100%;box-sizing:border-box;background:#1a1a1f;border:1px solid #3a3a44;color:#e8e6e0;
border-radius:6px;padding:8px 10px;font-size:13px;min-height:64px;font-family:inherit}}
.row{{display:flex;gap:12px}} .row > div{{flex:1}}
form.inline{{display:inline}} button.ghost{{background:#3a3a44}}
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
<button type="submit">Save LLM settings</button>
</div></form>

<form method="post" action="/settings/news">
<div class="section"><h2>News (Brave Search)</h2>
<label>Brave API key env var</label><input name="news_api_key_ref" value="{n_key_display}" placeholder="BRAVE_API_KEY">
<div class="hint">The Brave key is stored as an env-var reference or inline (masked, never shown). Never committed to the repo.</div>
<label>Brave API key (optional, inline — stored, never shown)</label><input name="news_api_key_raw" type="password" value="" placeholder="leave blank to keep current">
<label>Search queries (one per line)</label><textarea name="news_queries" placeholder="agent orchestration&#10;AI product management">{n_queries}</textarea>
<label>Product profile (what the relevance pass judges against)</label><textarea name="product_profile" placeholder="What the product is, who competes, what the PM cares about…">{n_profile}</textarea>
<div class="row">
<div><label>Max questions per run</label><input name="top_n" value="{n_top}"></div>
<div><label>Relevance threshold (0–1)</label><input name="min_relevance" value="{n_thresh}"></div>
</div>
<button type="submit">Save news settings</button>
</div></form>

<form method="post" action="/news/ingest" class="inline">
<div class="section"><h2>Fetch news now</h2>
<div class="hint">Runs a manual ingestion + relevance pass against your configured queries. (Cron scheduling comes later.)</div>
<button type="submit">Fetch news now</button>
</div></form>
</div></body></html>"""
