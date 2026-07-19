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
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pmqs import config
from pmqs.web import logo
from pmqs.web.markdown import render_markdown as _render_markdown

# --- Live wiring JS: injected into rendered pages so the template's buttons call the
# real backend endpoints instead of the demo's client-side stubs. Uses classic form
# POSTs (303 redirects) to match the server routes; no fetch/JSON needed. ---
def _live_js_common(prefix: str = "") -> str:
    """`prefix` (#56) is '' for the legacy unprefixed mount or '/w/{slug}' for a
    workspace-scoped page -- every action URL below is built against it so
    Save/Dismiss/War-room/nav clicks stay inside whichever workspace is being viewed."""
    return f"""
<script>
// PMQs live wiring (injected by render.py) — overrides the template's demo handlers.
function pmqsPost(action, fields){{
  const f = document.createElement('form');
  f.method = 'POST'; f.action = action;
  for (const k in (fields||{{}})){{
    const i = document.createElement('input');
    i.type = 'hidden'; i.name = k; i.value = fields[k];
    f.appendChild(i);
  }}
  document.body.appendChild(f); f.submit();
}}
function pmqsOpenWorkspace(qid){{ pmqsPost('{prefix}/workspace/open', {{question_id: qid || ''}}); }}
function pmqsSetStatus(qid, status){{ pmqsPost('{prefix}/questions/'+qid+'/status', {{status: status}}); }}
// Product switcher (#55): quiet open/close, no framework -- toggle a class, close on
// outside click or Escape. The menu's *content* (workspace list, current name) is
// server-rendered by render.py; this just controls visibility.
function pmqsToggleSwitcher(e){{
  if (e) e.stopPropagation();
  var el = document.getElementById('product-switcher');
  if (el) el.classList.toggle('open');
}}
document.addEventListener('click', function(e){{
  var el = document.getElementById('product-switcher');
  if (el && el.classList.contains('open') && !el.contains(e.target)) el.classList.remove('open');
}});
document.addEventListener('keydown', function(e){{
  if (e.key === 'Escape') {{
    var el = document.getElementById('product-switcher');
    if (el) el.classList.remove('open');
  }}
}});
// Make the top-nav Outcomes item load the real ledger page.
document.addEventListener('DOMContentLoaded', function(){{
  var nav = document.querySelector('.nav-item[data-nav="outcomes"]');
  if (nav) nav.addEventListener('click', function(e){{
    e.stopImmediatePropagation();
    window.location.href = '{prefix}/outcomes';
  }}, true);
  var inboxNav = document.querySelector('.nav-item[data-nav="inbox"]');
  if (inboxNav) inboxNav.addEventListener('click', function(){{ window.location.href = '{prefix}/'; }}, true);
  // §10.1: the Workspace nav opens a LIST of rooms, not whichever room was last open.
  var wsNav = document.querySelector('.nav-item[data-nav="workspace"]');
  if (wsNav) wsNav.addEventListener('click', function(e){{
    e.stopImmediatePropagation();
    window.location.href = '{prefix}/workspaces';
  }}, true);
}});
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

# Product switcher (#55): current-name text + the workspace-list region between the
# comment sentinels. Kept as its own small anchor pair rather than folded into the
# logo lockup splice, since it's spliced identically from three different render_*
# entry points (Inbox/Workspace/Outcomes) via _apply_product_switcher below.
_PS_CURRENT_RE = re.compile(
    r'(<div class="ps-current" id="ps-current" onclick="pmqsToggleSwitcher\(event\)">)(.*?)(<span class="ps-chevron">)',
    re.DOTALL,
)
_PS_ITEMS_RE = re.compile(
    r"(<!-- PRODUCT SWITCHER ITEMS -->)(.*?)(<!-- /PRODUCT SWITCHER ITEMS -->)", re.DOTALL
)
# Product settings hangs off the switcher, where products live -- account settings hangs
# off the identity block (#91). Two surfaces, two entry points, drawn on the same line:
# yours vs the product's.
_PS_SETTINGS_RE = re.compile(r'(<a class="ps-item" id="ps-settings" href=")[^"]*(")')


def _apply_product_switcher(src: str, db: Any, workspace_slug: str | None) -> str:
    """Splice the current product name + the list of the account's other products
    into the switcher markup. Safe to call even if the switcher markup isn't present
    (e.g. an older template) -- a 0-match splice is a silent no-op, not a crash, since
    unlike the load-bearing anchors in TEMPLATE-CONTRACT.md this one degrades to the
    static fixture rather than breaking the page.
    """
    from pmqs import products

    all_products = products.list_products(db)
    if not all_products:
        return src  # nothing to show yet (e.g. DB not initialised in this render path)

    current = None
    if workspace_slug is not None:
        current = next((p for p in all_products if p.slug == workspace_slug), None)
    if current is None:
        current = all_products[0]  # legacy unprefixed view -> account's default product

    current_name = html.escape(products.product_display_name(db, current))
    src = _PS_CURRENT_RE.sub(lambda m: f"{m.group(1)}\n            {current_name} {m.group(3)}", src, count=1)

    items = []
    for p in all_products:
        name = html.escape(products.product_display_name(db, p))
        cls = "ps-item current" if p.id == current.id else "ps-item"
        items.append(f'<a class="{cls}" href="/w/{p.slug}/">{name}</a>')
    items_html = "\n            ".join(items)
    src = _PS_ITEMS_RE.sub(lambda m: f"{m.group(1)}\n            {items_html}\n            {m.group(3)}", src, count=1)
    src = _PS_SETTINGS_RE.sub(lambda m: f"{m.group(1)}/w/{current.slug}/settings{m.group(2)}", src, count=1)
    return src


_IDENTITY_RE = re.compile(r"(<!-- IDENTITY -->)(.*?)(<!-- /IDENTITY -->)", re.DOTALL)


def _apply_identity(src: str, db: Any) -> str:
    """Splice the acting Member's name into the rail's identity block (#91).

    The block used to be a string literal in the template while a real Member row sat
    unrendered in the DB. Goes through members.current_member_id() -- the Phase 5 auth
    seam -- rather than reaching for the Member directly, so there stays exactly one
    function to replace when real identities attach.

    Like the switcher, a 0-match splice is a silent no-op: the block degrades to the
    template's static text rather than taking the page down.
    """
    from pmqs import members as members_repo
    from pmqs.models import Member

    member = db.get(Member, members_repo.current_member_id(db))
    if member is None:
        return src
    name = html.escape(member.display_name or members_repo.DEFAULT_MEMBER_DISPLAY_NAME)
    block = f"<b>{name}</b><br>Settings"
    return _IDENTITY_RE.sub(lambda m: f"{m.group(1)}{block}{m.group(3)}", src, count=1)


def _apply_rail(src: str, db: Any, workspace_slug: str | None) -> str:
    """The rail's two db-backed regions. Every render path draws the same rail, so they
    splice together rather than each caller remembering both."""
    return _apply_identity(_apply_product_switcher(src, db, workspace_slug), db)


def _load_template(template_path=None) -> str:
    """Read the app template and inject the logo mark."""
    src = Path(template_path or config.APP_TEMPLATE).read_text(encoding="utf-8")
    return src.replace(_LOGO_MARK_SENTINEL, logo.mark_svg(title=None), 1)


# Sentinel-anchored (#107). The previous version counted literal </div>s between the
# quick-add block and <!-- WORKSPACE VIEW -->, which meant group 2 silently swallowed
# every view in between -- by the time #view-workspaces landed it was eating that too.
# TEMPLATE-CONTRACT §6/§7: prefer sentinels over </div> counting.
_CARDS_REGION_RE = re.compile(
    r"(<!-- INBOX CARDS -->)(.*?)(<!-- /INBOX CARDS -->)",
    re.DOTALL,
)


def _pill(text: str, cls: str = "") -> str:
    c = f"pill {cls}".strip()
    return f'<span class="{c}">{html.escape(text)}</span>'


def _rel_age(created_at: str | None) -> str:
    """'2h' / '3d' / '5w' from an ISO timestamp. Empty string if unparseable."""
    if not created_at:
        return ""
    try:
        ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - ts).total_seconds()
    for div, suffix in ((60, "s"), (60, "m"), (24, "h"), (7, "d")):
        if secs < div:
            return f"{int(secs)}{suffix}"
        secs /= div
    return f"{int(secs)}w"


# #111: the Inbox detail pane and the Evidence tab render the same evidence object with
# different markup. One builder, two styles. The class names are NOT interchangeable --
# .evidence-item / .evidence-title / .evidence-sub are contract §4, so they are data here
# rather than something a caller can improvise.
#
# link_refs is the one genuine behavioural difference and it is preserved, not tidied:
# the Evidence tab renders a repo ref's URL as plain text while linking a news URL. That
# inconsistency predates this issue and #111 is scoped as a pure refactor, so it stays.
# Worth its own issue -- see the PR.
_SOURCE_STYLES = {
    #          wrapper           title             sub               link_refs
    "detail":   ("source-card",   "source-ref",     "source-meta",   True),
    "evidence": ("evidence-item", "evidence-title", "evidence-sub",  False),
}


def source_card_html(e: dict, style: str = "detail") -> str:
    """One evidence object as a card. `style` picks the class set and whether a
    non-news ref's URL is hyperlinked."""
    try:
        wrap, title_cls, sub_cls, link_refs = _SOURCE_STYLES[style]
    except KeyError:
        raise ValueError(f"unknown source-card style: {style!r}") from None

    url = html.escape(e.get("url", "") or "")
    if e.get("type") == "news":
        src = html.escape(e.get("source", "") or "source")
        title = html.escape(e.get("title", "") or "")
        date = html.escape(e.get("date", "") or "")
        ref = f"\u201c{title}\u201d" if title else "News item"
        meta = f"reportedly, via {src}" + (f" \u00b7 {date}" if date else "")
        link = f'<a href="{url}">{url}</a>' if url else ""
    else:
        ref = html.escape(f"{e.get('type', 'ref')} {e.get('ref', '')}".strip()) or "Reference"
        meta = ""
        link = (f'<a href="{url}">{url}</a>' if link_refs else url) if url else ""

    sub = " ".join(x for x in (meta, link) if x)
    return (
        f'<div class="{wrap}"><div class="{title_cls}">{ref}</div>'
        f'<div class="{sub_cls}">{sub}</div></div>'
    )


def question_detail_html(q: Any) -> str:
    """The Inbox detail pane for one question. Built server-side for every question in
    the list and shipped as JSON; selection swaps it in client-side (no per-selection
    round trip). Server-built so escaping stays in one place and #111 has a seam."""
    qid = html.escape(str(getattr(q, "id", "") or ""))
    title = html.escape(getattr(q, "title", "") or "")

    ev = getattr(q, "evidence_list", None)
    if ev is None:
        ev = getattr(q, "evidence", []) or []

    lens_tags = getattr(q, "lens_tags_list", None)
    if lens_tags is None:
        lens_tags = getattr(q, "lens_tags", []) or []
    pills = [_pill(t.replace("_", " ")) for t in lens_tags]
    age = _rel_age(getattr(q, "created_at", None))
    if age:
        pills.append(f'<span class="card-age">{html.escape(age)}</span>')

    if ev:
        source = source_card_html(ev[0])
        # Splice the lens pills + age into the shared card's meta row.
        source = source.replace(
            '<div class="source-meta">', f'<div class="source-meta">{" ".join(pills)} ', 1
        )
    else:
        source = (
            '<div class="source-card"><div class="source-ref">No evidence bound yet.</div>'
            f'<div class="source-meta">{" ".join(pills)}</div></div>'
        )

    desc = getattr(q, "description", None)
    context = (
        f'<div class="detail-body">{html.escape(str(desc))}</div>'
        if desc else
        '<div class="detail-body" style="color:var(--text-muted)">No description recorded '
        'for this question.</div>'
    )

    return (
        f'<div class="detail-title">{title}</div>'
        + source
        + '<div class="detail-section"><div class="detail-label">Context</div>'
        + context
        + "</div>"
        + '<div class="detail-actions">'
        + f'<button class="d-btn primary" onclick="pmqsOpenWorkspace(\'{qid}\')">Open workspace</button>'
        + f'<button class="d-btn" onclick="pmqsSetStatus(\'{qid}\',\'saved\')">Save</button>'
        + f'<button class="d-btn" onclick="pmqsSetStatus(\'{qid}\',\'dismissed\')">Dismiss</button>'
        + "</div>"
    )


def question_card_html(q: Any, rank: int | None = None) -> str:
    """Render one Question into the template's .card markup.

    `rank` (#110) is the row's 1-based index in the already-sorted list. It is position,
    not magnitude -- the `score N.NN` pill remains the magnitude. Nothing is recomputed
    here; the caller's ordering is the whole input.
    """
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

    # #110: the Inbox claims a ranked list; ordering was the only tell.
    badge = ""
    if rank is not None:
        top = " top" if rank <= 2 else ""
        badge = f'<span class="rank-badge{top}">{rank}</span>'

    qid = html.escape(str(getattr(q, "id", "") or ""))
    saved_style = ' style="margin-top:22px;"' if variant == "saved" else ""
    # data-qid + click SELECTS this question and swaps the detail pane (#107). The ⚔
    # icon-btn below still navigates straight to the war-room, so the old path stays.
    return f"""        <div class="card {variant}"{saved_style} data-qid="{qid}" onclick="pmqsSelect('{qid}')">
          <div class="card-main">
            <div class="card-title">{badge}{title}</div>
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
                 refresh: str | None = None,
                 db: Any = None, workspace_slug: str | None = None) -> str:
    """Return the full app HTML with Inbox fixture cards replaced by real ones.

    `refresh` (optional): the opaque report token minted by POST /refresh — one
    unified pass over every data source (repo triggers + news). Decoded here into a
    per-source banner that says what each source did and *why* it produced nothing
    when it did. See refresh.RefreshReport and _refresh_report_banner.
    `db`/`workspace_slug` (optional, #55/#56): when given, splices the Product switcher
    (current name + other workspaces) and makes quick-add/refresh/filter actions target
    this workspace's own /w/{slug}/... routes instead of the legacy unprefixed ones.
    """
    src = _load_template(template_path)
    if db is not None:
        src = _apply_rail(src, db, workspace_slug)

    banner = _refresh_report_banner(refresh)
    if questions:
        cards_html = banner + "\n\n".join(
            question_card_html(q, rank=i) for i, q in enumerate(questions, start=1)
        )
    else:
        # Explicit empty-state with an action — do NOT silently swap to a different
        # data source (that caused the home-page-changes-after-war-room bug).
        cards_html = banner + (
            '        <div class="card system"><div class="card-main">'
            '<div class="card-title">Your Inbox is empty.</div>'
            '<div class="card-meta">Refresh to collect from the repo and your news watchlist, or add your own above.</div>'
            '</div>'
            '<div class="card-actions" onclick="event.stopPropagation()">'
            '<div class="icon-btn primary" title="Refresh — collect from repo + news" onclick="pmqsRefresh()">⟳</div>'
            '</div></div>'
        )

    def _replace(m: re.Match) -> str:
        return f"{m.group(1)}\n\n{cards_html}\n{m.group(3)}"

    new_src, n = _CARDS_REGION_RE.subn(_replace, src)
    if n == 0:
        raise RuntimeError("Could not locate Inbox card region in app template")

    # Always-visible Refresh control in the Inbox header: runs the unified refresh
    # (repo structural triggers + news ingest/promotion). Replaces the plain "Inbox" header.
    header_html = (
        '<div class="inbox-header" style="display:flex;align-items:center;gap:12px;'
        'justify-content:space-between;">'
        '<span>Inbox</span>'
        '<button onclick="pmqsRefresh()" title="Refresh — collect from the repo and news watchlist" '
        'style="background:#4a7d6e;color:#fff;border:0;border-radius:6px;padding:6px 14px;'
        'font-size:12.5px;cursor:pointer;">⟳ Refresh</button>'
        '</div>'
    )
    new_src, hn = re.subn(r'<div class="inbox-header">Inbox</div>', header_html, new_src)
    # (hn==0 tolerated: header markup changed; the empty-state button still works.)

    # #107: the detail pane is hydrated client-side from a JSON blob carrying every
    # question's pre-rendered detail HTML. Rendered once, server-side, for the whole list
    # -- selection is a swap, not a round trip. "</" is escaped so a question title can
    # never close the script tag early.
    payload = json.dumps(
        {str(getattr(q, "id", "") or ""): question_detail_html(q) for q in questions}
    ).replace("</", "<\\/")
    detail_json = f'<script type="application/json" id="pmqs-question-detail">{payload}</script>'

    # Wire quick-add + card clicks to real endpoints (override template demo JS).
    # Also force the Inbox view active on load so no war-room/workspace header bleeds in.
    _prefix = f"/w/{workspace_slug}" if workspace_slug else ""
    inbox_js = detail_json + _live_js_common(_prefix) + f"""
<script>
// #107: two-pane Inbox. Selecting a card swaps the detail pane; no navigation.
var pmqsDetail = {{}};
try {{
  var _blob = document.getElementById('pmqs-question-detail');
  if (_blob) pmqsDetail = JSON.parse(_blob.textContent);
}} catch (e) {{ pmqsDetail = {{}}; }}

function pmqsSelect(qid){{
  var pane = document.getElementById('inbox-detail');
  if (!pane) return;
  document.querySelectorAll('#view-inbox .card').forEach(function(c){{
    c.classList.toggle('selected', c.getAttribute('data-qid') === qid);
  }});
  pane.innerHTML = pmqsDetail[qid] ||
    '<div class="detail-empty">This question is no longer in the list.</div>';
}}

document.addEventListener('DOMContentLoaded', function(){{
  var pane = document.getElementById('inbox-detail');
  var first = document.querySelector('#view-inbox .card[data-qid]');
  if (first && first.getAttribute('data-qid')) {{
    pmqsSelect(first.getAttribute('data-qid'));   // first card selected on load
  }} else if (pane) {{
    pane.innerHTML = '<div class="detail-empty">Nothing to triage. ' +
      'Refresh to collect from the repo and news, or add your own.</div>';
  }}
}});
// Override quick-add to create a real PM question server-side.
function addQuestion(){{
  var input = document.getElementById('quick-add-input');
  var val = (input && input.value || '').trim();
  if(!val) return;
  pmqsPost('{_prefix}/quick-add', {{title: val}});
}}
function pmqsRefresh(){{ pmqsPost('{_prefix}/refresh', {{}}); }}
// The home page is always the Inbox — never leave another view active.
document.addEventListener('DOMContentLoaded', function(){{
  if (typeof showView === 'function') showView('inbox');
  // H2: wire filter pills to server-side filtering (?source=).
  var map = {{all: '{_prefix}/', asked: '{_prefix}/?source=pm', system: '{_prefix}/?source=system'}};
  document.querySelectorAll('.filter-pill').forEach(function(p){{
    var f = p.getAttribute('data-filter');
    if (map[f] !== undefined) {{
      p.addEventListener('click', function(e){{
        e.stopImmediatePropagation();
        window.location.href = map[f];
      }}, true);
    }}
  }});
}});
</script>
"""
    return _inject_before_body_close(new_src, inbox_js)


# Per-source refresh copy. Each code maps to a plain-English line; the {detail} slot
# (already-safe, escaped at render) carries the specifics (issue counts, which env var,
# etc). `warn=True` sources render amber (a fixable problem) rather than teal (fine).
_REPO_LINES = {
    "generated": ("ok", "Repo: {count} new from structural triggers."),
    "clean": ("ok", "Repo: nothing to raise — {detail}."),
    "error": ("warn", "Repo: couldn't read the repo — {detail}."),
}
_NEWS_LINES = {
    "promoted": ("ok", "News: {count} new — {detail}."),
    "disabled": ("warn", "News: turned off in Settings."),
    "no_key": ("warn", "News: no Brave API key — {detail} (Settings \u2192 News)."),
    "no_products": ("warn", "News: no products configured."),
    "no_watchlist": ("warn", "News: no watchlist terms — add companies/keywords in a product's Settings."),
    "fetched_llm_off": ("warn", "News: {detail} — set an LLM provider in Settings."),
    "no_profile": ("warn", "News: no product profile set — add one in the product's Settings so news can be judged against it."),
    "news_llm_error": ("warn", "News: the relevance check couldn't run — {detail}."),
    "nothing_new": ("ok", "News: no new stories for your watchlist."),
    "nothing_relevant": ("ok", "News: {detail}."),
    "error": ("warn", "News: fetch failed — {detail}."),
}


def _refresh_line(table: dict, res) -> tuple[str, str]:
    """(kind, text) for one source result. kind ∈ {'ok','warn'}."""
    kind, tmpl = table.get(res.code, ("ok", ""))
    if not tmpl:
        return kind, ""
    text = tmpl.format(count=res.count, detail=html.escape(res.detail or ""))
    return kind, text


def _refresh_report_banner(token: str | None) -> str:
    """One Inbox banner summarising the last unified Refresh, source by source.

    Decodes the report token from POST /refresh. The headline states the net result;
    the sub-lines explain each source so a legitimate zero (clean repo, quiet
    watchlist, missing key) reads as an explanation, not a broken button. Any source
    flagged `warn` tints the whole banner amber so a fixable problem stands out.
    """
    from pmqs.refresh import RefreshReport

    report = RefreshReport.decode(token) if token else None
    if report is None:
        return ""

    repo_kind, repo_text = _refresh_line(_REPO_LINES, report.repo)
    news_kind, news_text = _refresh_line(_NEWS_LINES, report.news)
    lines = [t for t in (repo_text, news_text) if t]
    if not lines:
        return ""

    total = report.total
    if total:
        headline = f"Refresh complete — {total} new question{'s' if total != 1 else ''}."
    else:
        headline = "Refresh complete — no new questions."

    any_warn = "warn" in (repo_kind, news_kind)
    accent = "#b8860b" if any_warn else "#4a7d6e"  # amber if anything needs attention
    body = "".join(f'<div class="card-meta">{t}</div>' for t in lines)
    return (
        f'        <div class="card system" style="border-left:3px solid {accent};">'
        f'<div class="card-main"><div class="card-title">{html.escape(headline)}</div>'
        f'{body}</div></div>\n\n'
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
    r'(<div id="tab-proposed"[^>]*>)(.*?)(</div>\s*<div id="tab-draft")', re.DOTALL
)
_STATS_RE = re.compile(r'(<span class="session-stats">).*?(</span>)', re.DOTALL)


def _tab_label_re(tab: str) -> re.Pattern:
    """#108: anchor on the data-tab value (already contract, §3) rather than on nesting,
    so the count can go in the label without touching the artifact pane's structure."""
    return re.compile(r'(data-tab="%s"[^>]*>)([^<]*)(</div>)' % re.escape(tab))


def _apply_tab_counts(src: str, counts: dict[str, int]) -> str:
    """Put the item count in the tab label -- Evidence (4), Proposed (2). Renders (0)
    when empty rather than hiding, so an empty pane is a fact rather than an absence.
    Only the countable tabs get one: 'Position document' and 'Impacts' are single
    artifacts, not lists."""
    for tab, n in counts.items():
        def _sub(m: re.Match) -> str:
            label = re.sub(r"\s*\(\d+\)$", "", m.group(2).strip())
            return f"{m.group(1)}{label} ({n}){m.group(3)}"
        src, hit = _tab_label_re(tab).subn(_sub, src, count=1)
        if not hit:
            raise RuntimeError(f"Could not locate the '{tab}' artifact tab in app template")
    return src


def _initials(label: str) -> str:
    """'You' -> 'Y', 'War-room' -> 'WR'. Split on non-letters so hyphens count."""
    words = [w for w in re.split(r"[^A-Za-z]+", label) if w]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def render_event_line(label: str, tab: str | None = None) -> str:
    """The activity-log line markup for a label (+ optional artifact tab). Shared by the
    server-rendered conversation and the async endpoints (Wave 2), so a live-appended
    event looks identical to one rendered on load."""
    attrs = ""
    cls = "msg event"
    if tab:
        cls += " event-open"
        attrs = f" onclick=\"showTab('{html.escape(str(tab))}')\" title=\"Open the artifact\""
    return (
        f'<div class="{cls}"{attrs}>'
        f'<div class="event-line">{html.escape(str(label))}</div>'
        f"</div>"
    )


def _event_html(m: Any) -> str:
    """An activity-log line in the conversation (role='event'). Quiet, tool-call styled,
    and click-to-open the matching artifact tab when the event carries one."""
    import json as _json
    try:
        payload = _json.loads(getattr(m, "content", "") or "{}")
    except (ValueError, TypeError):
        payload = {}
    return render_event_line(payload.get("label") or "Activity", payload.get("tab"))


def render_message_html(m: Any) -> str:
    """Public wrapper: render one conversation message (used by async /message)."""
    return _msg_html(m)


def render_proposed_tab_html(proposed: list[Any], session_id: str = "") -> str:
    """Public wrapper: the Proposed-questions tab inner HTML (async /run-lenses)."""
    return _proposed_html(proposed, session_id)


def render_position_doc_tab_html(doc: dict | None) -> str:
    """Public wrapper: the Position-document tab inner HTML (async /position-doc)."""
    return _position_doc_html(doc)


def _msg_html(m: Any) -> str:
    role = getattr(m, "role", "system")
    if role == "event":
        return _event_html(m)
    cls = "pm" if role == "pm" else "system"
    label = "You" if role == "pm" else ("System" if role == "system" else "War-room")
    bubble = "pm-bubble" if role == "pm" else "sys-bubble"
    # PM turns are user input → escape as plain text. The war-room reply (and system
    # notes) are Markdown → render the safe subset so bold/lists/source links show.
    raw = getattr(m, "content", "")
    body = html.escape(raw) if role == "pm" else _render_markdown(raw)
    # #109: avatar + .msg-col are new children of .msg. Safe because _CONVO_RE replaces
    # the whole .convo-scroll region -- it anchors on that class and .convo-input, not on
    # anything inside a message. The template's CSS is changed in the same commit.
    return (
        f'<div class="msg {cls}">'
        f'<div class="msg-avatar">{html.escape(_initials(label))}</div>'
        f'<div class="msg-col"><div class="msg-label">{label}</div>'
        f'<div class="msg-body {bubble}">{body}</div>'
        f"</div></div>"
    )


def _evidence_html(evidence: list[dict]) -> str:
    if not evidence:
        return '<div class="evidence-item"><div class="evidence-title">No evidence bound yet.</div></div>'
    return "\n".join(source_card_html(e, style="evidence") for e in evidence)


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
        + "</div>"
        + _prior_decisions_html(doc.get("prior_decisions") or [])
        + "</div>"
    )


def _prior_decisions_html(cites: list) -> str:
    """The [prior N] citations the doc's text refers to, with author and date.

    Item 10's acceptance is that prior decisions "appear cited with author and date" --
    an inline [prior 0] with nothing to resolve it against is not a citation. Reuses
    .doc-section/.doc-label/.doc-text and --text-muted; no new colour token, so the §11
    brand drift guards stay green.
    """
    if not cites:
        return ""
    rows = "".join(
        f'<div class="ledger-src">[prior {html.escape(str(c.get("ref")))}] '
        f'{html.escape(str(c.get("type", "")))} — decided by '
        f'{html.escape(str(c.get("author", "Unknown")))} on '
        f'{html.escape(str(c.get("date", "")))}: '
        f'{html.escape(str(c.get("text", ""))[:200])}</div>'
        for c in cites
    )
    return (
        '<div class="doc-section"><div class="doc-label">Prior decisions cited</div>'
        f'<div class="doc-text">{rows}</div></div>'
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
    db: Any = None,
    workspace_slug: str | None = None,
) -> str:
    """Splice real war-room session data into the template's Workspace view.

    Preserves all CSS/JS and the Inbox/Outcomes views. Replaces: ws-title, conversation
    messages, position-doc tab, evidence tab, proposed-questions tab, and session stats.
    `db`/`workspace_slug` (#55): splices the Product switcher so it shows which product
    this session belongs to, same as Inbox/Outcomes.
    """
    src = _load_template(template_path)
    if db is not None:
        src = _apply_rail(src, db, workspace_slug)

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
    # #108: counts come from the same lists spliced into the panes above, so the label
    # can never disagree with the pane's contents.
    src = _apply_tab_counts(src, {"evidence": len(evidence), "proposed": len(proposed)})

    src, n = _STATS_RE.subn(
        lambda m: f'{m.group(1)}<span id="sess-count">{n_exchanges}</span> exchanges{m.group(2)}', src
    )
    if n == 0:
        raise RuntimeError("Could not locate Workspace region: session-stats")

    # Inject session-aware live wiring: override the template's demo handlers so the
    # war-room buttons hit real endpoints for THIS session.
    sid = session.id
    ws_js = _live_js_common() + f"""
<script>
var PMQS_SID = {sid!r};

// --- Wave 2: async actions with a live activity log + busy indicator ---
function pmqsAjax(action, fields){{
  var body = new URLSearchParams();
  for (var k in (fields||{{}})) body.set(k, fields[k]);
  return fetch(action, {{
    method:'POST',
    headers:{{'Content-Type':'application/x-www-form-urlencoded','X-PMQS-Ajax':'1'}},
    body: body.toString()
  }}).then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok, j:j}}; }}); }});
}}
function pmqsConvoScroll(){{ var s=document.getElementById('convo-scroll'); if(s) s.scrollTop=s.scrollHeight; }}
function pmqsAppendHTML(htmlStr){{
  var s=document.getElementById('convo-scroll'); if(!s||!htmlStr) return null;
  var t=document.createElement('template'); t.innerHTML=String(htmlStr).trim();
  var node=t.content.firstChild; if(node){{ s.appendChild(node); pmqsConvoScroll(); }}
  return node;
}}
function pmqsBusy(on){{
  var pane=document.querySelector('.convo-pane'); if(pane) pane.classList.toggle('convo-busy', !!on);
}}
// Mirror the busy state on the artifact pane (Wave 3): a spinner in the tab bar while
// the right side is generating a draft or position document.
function pmqsPaneBusy(on){{
  var tabs=document.querySelector('.artifact-tabs'); if(tabs) tabs.classList.toggle('tabs-busy', !!on);
}}
// A transient busy line in the conversation; returns the node so it can be replaced.
function pmqsBusyLine(text){{
  return pmqsAppendHTML('<div class="msg event"><div class="event-line"><span class="event-spinner"></span>'+text+'</div></div>');
}}
function pmqsRefreshTab(tab, html, count){{
  if(!tab) return;
  var pane=document.getElementById('tab-'+tab); if(pane && html!=null) pane.innerHTML=html;
  if(count!=null){{
    var lbl=document.querySelector('.a-tab[data-tab="'+tab+'"]');
    if(lbl){{ lbl.textContent = lbl.textContent.replace(/\\s*\\(\\d+\\)\\s*$/, '') + ' (' + count + ')'; }}
  }}
}}

function sendMsg(){{
  var input = document.getElementById('chat-input');
  var val = (input && input.value || '').trim();
  if(!val) return;
  // Optimistic PM bubble (built via DOM, textContent = XSS-safe), then a busy line.
  var s=document.getElementById('convo-scroll');
  if(s){{
    var wrap=document.createElement('div'); wrap.className='msg pm';
    var av=document.createElement('div'); av.className='msg-avatar'; av.textContent='You';
    var col=document.createElement('div'); col.className='msg-col';
    var lab=document.createElement('div'); lab.className='msg-label'; lab.textContent='You';
    var bod=document.createElement('div'); bod.className='msg-body pm-bubble'; bod.textContent=val;
    col.appendChild(lab); col.appendChild(bod); wrap.appendChild(av); wrap.appendChild(col);
    s.appendChild(wrap); pmqsConvoScroll();
  }}
  input.value=''; pmqsBusy(true);
  var busy = pmqsBusyLine('War-room is thinking…');
  pmqsAjax('/workspace/'+PMQS_SID+'/message', {{content: val}})
    .then(function(res){{
      if(busy) busy.remove();
      if(res.ok && res.j.assistant_html) pmqsAppendHTML(res.j.assistant_html);
      else pmqsAppendHTML('<div class="msg event"><div class="event-line">✕ message failed</div></div>');
      var c=document.getElementById('sess-count'); if(c) c.textContent=(parseInt(c.textContent||'0',10)||0)+1;
    }})
    .catch(function(){{ if(busy) busy.remove(); pmqsAppendHTML('<div class="msg event"><div class="event-line">✕ network error</div></div>'); }})
    .finally(function(){{ pmqsBusy(false); }});
}}
function pmqsRunLenses(){{
  pmqsBusy(true);
  var busy = pmqsBusyLine('Running 8-lens pass…');
  pmqsAjax('/workspace/'+PMQS_SID+'/run-lenses', {{}})
    .then(function(res){{
      if(busy) busy.remove();
      if(res.ok){{ pmqsAppendHTML(res.j.event_html); pmqsRefreshTab(res.j.tab, res.j.tab_html, res.j.tab_count); }}
      else pmqsAppendHTML('<div class="msg event"><div class="event-line">✕ lens pass failed</div></div>');
    }})
    .catch(function(){{ if(busy) busy.remove(); }})
    .finally(function(){{ pmqsBusy(false); }});
}}
function pmqsGenDoc(){{
  pmqsBusy(true); pmqsPaneBusy(true);
  var busy = pmqsBusyLine('Generating position document…');
  pmqsAjax('/workspace/'+PMQS_SID+'/position-doc', {{}})
    .then(function(res){{
      if(busy) busy.remove();
      if(res.ok){{ if(res.j.event_html) pmqsAppendHTML(res.j.event_html); pmqsRefreshTab(res.j.tab, res.j.tab_html, null); }}
      else pmqsAppendHTML('<div class="msg event"><div class="event-line">✕ generation failed</div></div>');
    }})
    .catch(function(){{ if(busy) busy.remove(); }})
    .finally(function(){{ pmqsBusy(false); pmqsPaneBusy(false); }});
}}
function pmqsAddProposed(qid, btn){{ pmqsPost('/workspace/'+PMQS_SID+'/proposed/'+qid+'/add', {{}}); }}
// Outcome bar → real typed-outcome endpoint, rendered INLINE (no navigation).
// Wave 1: this replaces the old full-page form submit that dumped the PM on a raw
// JSON blob. The receipt says what was made and links to where it now lives.
function pmqsOutcomeReceipt(text, url, linkLabel, ok){{
  var log = document.getElementById('outcomes-log');
  if(!log) return;
  var span = document.createElement('span');
  span.className = 'chip ' + (ok ? 'record' : 'issue');
  span.textContent = text;
  if(url){{
    var a = document.createElement('a');
    a.href = url; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = ' ' + (linkLabel || 'open');
    a.style.marginLeft = '6px';
    span.appendChild(a);
  }}
  log.appendChild(span);
}}
var PMQS_FIELD_LABELS = {{title:'Title', body:'Body', agenda:'Agenda', text:'Standing rule'}};

// Commit an outcome with its (edited) fields → Wave 1 receipt.
function pmqsCommitOutcome(type, fields){{
  var body = new URLSearchParams();
  body.set('type', type);
  if(fields.title) body.set('title', fields.title);
  if(fields.body) body.set('body', fields.body);
  if(fields.agenda) body.set('agenda', fields.agenda);
  if(fields.calendar_link) body.set('calendar_link', fields.calendar_link);
  if(type === 'policy') body.set('body', fields.text || fields.body || fields.title || '');
  fetch('/workspace/'+PMQS_SID+'/outcome', {{
    method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body: body.toString()
  }}).then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok, j:j}}; }}); }})
    .then(function(res){{
      var tname = type.charAt(0).toUpperCase()+type.slice(1);
      if(!res.ok){{ pmqsOutcomeReceipt('✕ ' + ((res.j && res.j.error) || ('could not create ' + type)), null, null, false); return; }}
      var j = res.j; var loc = j.location || {{}};
      pmqsOutcomeReceipt('✓ ' + tname + ' created — ' + (j.title || fields.title || ''), loc.url, loc.label, true);
      // Wave 3: portability — a Document/Meeting can be taken anywhere as Markdown.
      if(j.export_url) pmqsOutcomeReceipt('⤓ ' + tname, j.export_url + '?download=1', 'Download .md', true);
      var badge = document.getElementById('ws-badge');
      if(badge) badge.textContent = (parseInt(badge.textContent||'0',10)||0) + 1;
      var host = document.getElementById('draft-body');
      if(host) host.innerHTML = '<div class="draft-empty">' + tname + ' committed. Pick another outcome below to draft again.</div>';
    }})
    .catch(function(){{ pmqsOutcomeReceipt('✕ network error creating ' + type, null, null, false); }});
}}

// Render the editable draft into the Draft tab.
function pmqsRenderDraft(type, fields, degraded){{
  var host = document.getElementById('draft-body');
  if(!host) return;
  host.innerHTML = '';
  var tname = type.charAt(0).toUpperCase()+type.slice(1);
  var head = document.createElement('div');
  head.className = 'draft-note';
  head.textContent = degraded
    ? ('Draft ' + tname + ': the model was unreachable — write it yourself, then commit.')
    : ('Draft ' + tname + ' — generated from this session. Edit anything, then commit.');
  host.appendChild(head);
  var inputs = {{}};
  Object.keys(fields).forEach(function(k){{
    var wrap = document.createElement('div'); wrap.className = 'draft-field';
    var lbl = document.createElement('div'); lbl.className = 'draft-field-label';
    lbl.textContent = PMQS_FIELD_LABELS[k] || k; wrap.appendChild(lbl);
    var el;
    if(k === 'title'){{ el = document.createElement('input'); el.className = 'draft-input'; el.type = 'text'; }}
    else {{ el = document.createElement('textarea'); el.className = 'draft-textarea'; }}
    el.value = fields[k] || ''; wrap.appendChild(el); host.appendChild(wrap);
    inputs[k] = el;
  }});
  // Wave 3: a Meeting can optionally carry a calendar link (passthrough, not generated).
  if(type === 'meeting'){{
    var cwrap = document.createElement('div'); cwrap.className = 'draft-field';
    var clbl = document.createElement('div'); clbl.className = 'draft-field-label';
    clbl.textContent = 'Calendar link (optional)'; cwrap.appendChild(clbl);
    var cel = document.createElement('input'); cel.className = 'draft-input'; cel.type = 'text';
    cel.placeholder = 'paste a calendar event URL'; cwrap.appendChild(cel); host.appendChild(cwrap);
    inputs['calendar_link'] = cel;
  }}
  var actions = document.createElement('div'); actions.className = 'draft-actions';
  var commit = document.createElement('button'); commit.className = 'p-add'; commit.textContent = 'Commit ' + tname;
  commit.onclick = function(){{
    var out = {{}}; Object.keys(inputs).forEach(function(k){{ out[k] = inputs[k].value; }});
    pmqsCommitOutcome(type, out);
  }};
  var discard = document.createElement('button'); discard.className = 'p-dismiss'; discard.textContent = 'Discard';
  discard.onclick = function(){{ host.innerHTML = '<div class="draft-empty">Draft discarded. Pick an outcome below to draft again.</div>'; }};
  actions.appendChild(commit); actions.appendChild(discard); host.appendChild(actions);
}}

// Draft-first (Wave 2): generate from context, show in the Draft tab, let the PM edit.
function pmqsDraft(type){{
  var host = document.getElementById('draft-body');
  var tname = type.charAt(0).toUpperCase()+type.slice(1);
  if(host) host.innerHTML = '<div class="draft-empty">Drafting ' + type + ' from this session…</div>';
  if(typeof showTab === 'function') showTab('draft');
  // Interplay Wave 3: the draft path narrates itself in the conversation, with a busy
  // line that resolves into a click-to-open "draft ready" event.
  pmqsPaneBusy(true);
  var busy = (typeof pmqsBusyLine === 'function') ? pmqsBusyLine('Drafting ' + type + ' from this session…') : null;
  var body = new URLSearchParams(); body.set('type', type);
  fetch('/workspace/'+PMQS_SID+'/draft', {{
    method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body: body.toString()
  }}).then(function(r){{ return r.json(); }})
    .then(function(j){{
      if(busy) busy.remove();
      if(j && j.fields){{
        pmqsRenderDraft(j.type || type, j.fields, !!j.degraded);
        if(typeof pmqsAppendHTML === 'function')
          pmqsAppendHTML('<div class="msg event event-open" onclick="showTab(\\'draft\\')" title="Open the artifact">'
            + '<div class="event-line">✎ ' + tname + ' draft ready — review and commit</div></div>');
      }} else if(host){{ host.innerHTML = '<div class="draft-empty">Could not draft ' + type + '.</div>'; }}
    }})
    .catch(function(){{ if(busy) busy.remove(); if(host){{ host.innerHTML = '<div class="draft-empty">Network error drafting ' + type + '.</div>'; }} }})
    .finally(function(){{ pmqsPaneBusy(false); }});
}}

// Outcome-bar buttons are now draft-first: draft → edit → commit.
function addOutcome(type){{ pmqsDraft(type); }}

// Wrap up (Wave 4): suggest the best outcome, and offer to close with a reason so a
// no-outcome exit is a signal, not a mystery. Suggestion never creates anything.
var PMQS_CLOSE_REASONS = [
  ['no_decision_yet', 'No decision needed yet'],
  ['decided_nothing_to_record', 'Decided — nothing to record'],
  ['couldnt_get_what_i_needed', "Couldn't get what I needed"]
];
function pmqsRenderWrapup(sugg){{
  var panel = document.getElementById('wrapup-panel');
  if(!panel) return;
  panel.style.display = 'block';
  panel.innerHTML = '';
  var s = document.createElement('div'); s.className = 'wrapup-suggest';
  if(sugg && sugg.type){{
    var tname = sugg.type.charAt(0).toUpperCase()+sugg.type.slice(1);
    s.innerHTML = 'Suggested outcome: <b>' + tname + '</b> — <span class="wrapup-why"></span> ';
    s.querySelector('.wrapup-why').textContent = sugg.rationale || '';
    var draftBtn = document.createElement('button'); draftBtn.className = 'p-add';
    draftBtn.textContent = 'Draft it';
    draftBtn.onclick = function(){{ pmqsDraft(sugg.type); }};
    s.appendChild(draftBtn);
  }} else {{
    s.textContent = (sugg && sugg.rationale) || 'Pick the outcome that fits — PMQs drafts it from this session.';
  }}
  panel.appendChild(s);
  var lbl = document.createElement('div'); lbl.className = 'wrapup-label';
  lbl.textContent = 'Or close this room';
  panel.appendChild(lbl);
  var reasons = document.createElement('div'); reasons.className = 'wrapup-reasons';
  PMQS_CLOSE_REASONS.forEach(function(pair){{
    var b = document.createElement('button'); b.className = 'p-dismiss';
    b.textContent = pair[1];
    b.onclick = function(){{ pmqsCloseRoom(pair[0]); }};
    reasons.appendChild(b);
  }});
  panel.appendChild(reasons);
}}
function pmqsWrapUp(){{
  var panel = document.getElementById('wrapup-panel');
  if(panel && panel.style.display === 'block'){{ panel.style.display = 'none'; return; }}  // toggle
  if(panel){{ panel.style.display = 'block'; panel.innerHTML = '<div class="wrapup-suggest">Thinking about the best outcome…</div>'; }}
  var body = new URLSearchParams();
  fetch('/workspace/'+PMQS_SID+'/suggest-outcome', {{
    method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body: body.toString()
  }}).then(function(r){{ return r.json(); }})
    .then(function(j){{ pmqsRenderWrapup(j); }})
    .catch(function(){{ pmqsRenderWrapup(null); }});
}}
function pmqsCloseRoom(reason){{
  var body = new URLSearchParams(); body.set('reason', reason);
  fetch('/workspace/'+PMQS_SID+'/close', {{
    method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body: body.toString()
  }}).then(function(r){{ return r.json(); }})
    .then(function(){{
      var panel = document.getElementById('wrapup-panel');
      if(panel) panel.innerHTML = '<div class="wrapup-suggest">Room closed. Nothing was recorded — that reason is logged.</div>';
    }})
    .catch(function(){{}});
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


def _author_names(db: Any, outcomes: list) -> dict:
    """Map author_member_id -> display_name for a page of outcomes, in one query.

    The ledger grows monotonically (build-spec §12 "landfill"), so this resolves names in
    a single IN() rather than lazily per row -- a per-row lookup is an N+1 that gets
    slower exactly as the product succeeds.
    """
    from pmqs.models import Member

    ids = {o.author_member_id for o in outcomes if o.author_member_id}
    if not ids:
        return {}
    rows = db.query(Member).filter(Member.id.in_(ids)).all()
    return {m.id: m.display_name for m in rows}


_WORKSPACES_LIST_RE = re.compile(
    r'(<div id="workspaces-list">)(.*?)(</div>\s*</div>\s*</div>)', re.DOTALL
)


def _workspace_row_html(row: dict) -> str:
    """One Workspace list row (build-spec §10.1).

    Reuses .ledger-item/.ledger-main/.ledger-src/.ledger-time and existing tokens -- no
    new colour token, so the §11 drift guards stay green. Per §10.1 hue carries state,
    not identity: rows are NOT coloured, and "private" is a word rather than a hue.
    """
    name = html.escape(row["name"])
    meta = f'{html.escape(row["owner_name"])} · {row["outcome_count"]} outcome'
    meta += "" if row["outcome_count"] == 1 else "s"
    if row["is_private"]:
        meta += " · private"
    return (
        f'<div class="ledger-item" data-ws-id="{html.escape(row["session"].id)}" '
        f'onclick="pmqsOpenRoom(\'{html.escape(row["session"].id)}\')">'
        f'<div class="ledger-main">{name}<div class="ledger-src">{meta}</div></div>'
        f'<span class="ledger-time">{html.escape((row["last_modified"] or "")[:10])}</span>'
        f"</div>"
    )


def render_workspace_list(
    db: Any,
    rows: list[dict],
    template_path: Path | None = None,
    *,
    owner: str = "any",
    workspace_slug: str | None = None,
) -> str:
    """The Workspace nav item's list view (build-spec §10.1), modelled on Google Docs.

    Private Workspaces are ABSENT for non-owners rather than redacted -- see
    repository.list_workspace_rows. The filter chips are server-rendered links, not
    client-side filtering, so the visibility rules are enforced in SQL every time rather
    than shipping every row to the browser and hiding some with CSS.
    """
    src = _load_template(template_path)
    src = _apply_rail(src, db, workspace_slug)

    items = [_workspace_row_html(r) for r in rows]
    body = "\n".join(items) if items else (
        '<div class="ledger-item"><div class="ledger-main">No workspaces yet.</div></div>'
    )
    new_src, n = _WORKSPACES_LIST_RE.subn(lambda m: f"{m.group(1)}{body}{m.group(3)}", src)
    if n == 0:
        raise RuntimeError("Could not locate Workspaces list region in app template")

    # Mark the active filter chip.
    for key in ("any", "mine", "not_mine"):
        cls = "filter-pill active" if key == owner else "filter-pill"
        new_src = new_src.replace(
            f'<div class="filter-pill active" data-ws-owner="{key}">',
            f'<div class="{cls}" data-ws-owner="{key}">',
        ).replace(
            f'<div class="filter-pill" data-ws-owner="{key}">',
            f'<div class="{cls}" data-ws-owner="{key}">',
        )

    _prefix = f"/w/{workspace_slug}" if workspace_slug else ""
    js = _live_js_common(_prefix) + f"""
<script>
function pmqsOpenRoom(sid){{ window.location.href = '{_prefix}/workspace/' + sid; }}
document.addEventListener('DOMContentLoaded', function(){{
  // Activate this view directly rather than via showView(): the room view and the list
  // view share one nav item, so showView's nav lookup doesn't map 1:1 here.
  document.querySelectorAll('.view').forEach(function(v){{ v.classList.remove('active'); }});
  var el = document.getElementById('view-workspaces');
  if (el) el.classList.add('active');
  document.querySelectorAll('.nav-item').forEach(function(n){{ n.classList.remove('active'); }});
  var nav = document.querySelector('.nav-item[data-nav="workspace"]');
  if (nav) nav.classList.add('active');
  document.querySelectorAll('[data-ws-owner]').forEach(function(c){{
    c.addEventListener('click', function(){{
      window.location.href = '{_prefix}/workspaces?owner=' + c.dataset.wsOwner;
    }});
  }});
}});
</script>
"""
    return new_src.replace("</body>", js + "</body>")


def _ledger_item_html(o: Any, payload: dict, author: str | None = None) -> str:
    """One ledger row.

    `author` renders the "who decided this" half of Wave 1/2's whole point: the ledger is
    Product-scoped, so a row may well be a colleague's. It rides the existing .ledger-src
    line and --text-muted rather than introducing a surface of its own -- no new colour
    token, so tests/test_brand_doc.py stays green (build-spec §11).

    NOTE: attribution here is per-outcome and never aggregated. Count outcomes, never
    rank people (§12 "attribution chilling"): if the ledger ever scores members, PMs stop
    recording the messy decisions and the ledger stops being worth reading.
    """
    otype = o.type
    tag = _LEDGER_TAG.get(otype, otype.title())
    title = html.escape(_outcome_title(otype, payload) or "(untitled)")
    src = "from war-room" + ("" if o.session_id else " · direct")
    if author:
        src += f" · {author}"
    if o.github_ref:
        ref = f'<div class="ledger-src"><a href="{html.escape(o.github_ref)}">{html.escape(o.github_ref)}</a>'
        if author:
            ref += f' · {html.escape(author)}'
        ref += '</div>'
    else:
        ref = f'<div class="ledger-src">{html.escape(src)}</div>'
    # Wave 3: portability affordances on the ledger. Document/Meeting get an export
    # link; a Meeting with a calendar_link gets an "Add to calendar" link. Reuses
    # .ledger-src + existing tokens, so the §11 brand drift guards stay green.
    extras = ""
    if otype in ("document", "meeting"):
        exp = f'/outcomes/{html.escape(o.id)}/export.md'
        links = f'<a href="{exp}" target="_blank" rel="noopener">Export .md</a>'
        cal = html.escape((payload.get("calendar_link") or "").strip())
        if otype == "meeting" and cal:
            links += f' · <a href="{cal}" target="_blank" rel="noopener">Add to calendar</a>'
        extras = f'<div class="ledger-src">{links}</div>'
    return (
        f'<div class="ledger-item" data-type="{otype}">'
        f'<span class="ledger-tag {otype}">{tag}</span>'
        f'<div class="ledger-main">{title}{ref}{extras}</div>'
        f'<span class="ledger-time"></span></div>'
    )


def render_outcomes(db: Any, template_path: Path | None = None, *, product_id: str | None = None,
                    workspace_slug: str | None = None) -> str:
    """Splice real outcome rows + summary counts into the template's Outcomes view.

    Mirrors the Inbox wiring: replace the static ledger fixtures and the summary-strip
    numbers with real data. Inbox/Workspace views preserved. `product_id` scopes the
    ledger to one product; omitted, it shows every product's outcomes -- the
    pre-multi-product behaviour existing callers still rely on. `workspace_slug`
    (#55) drives the Product switcher and keeps the Inbox-nav link inside the same
    product.
    """
    from pmqs import repository

    src = _load_template(template_path)
    src = _apply_rail(src, db, workspace_slug)
    # Product-scoped, visibility-filtered (build-spec §4/§5): every member's outcomes,
    # minus other members' private rooms. Already newest-first from the query.
    from pmqs import members as members_repo

    viewer_id = members_repo.current_member_id(db)
    outcomes = repository.list_ledger_outcomes(db, product_id=product_id, member_id=viewer_id)

    authors = _author_names(db, outcomes)
    counts = {"issue": 0, "policy": 0, "document": 0, "meeting": 0, "question": 0}
    items = []
    for o in outcomes:
        counts[o.type] = counts.get(o.type, 0) + 1
        items.append(
            _ledger_item_html(o, repository.outcome_payload(o), authors.get(o.author_member_id))
        )

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
    _prefix = f"/w/{workspace_slug}" if workspace_slug else ""
    outcomes_js = _live_js_common(_prefix) + """
<script>
document.addEventListener('DOMContentLoaded', function(){
  if (typeof showView === 'function') showView('outcomes');
});
</script>
"""
    return _inject_before_body_close(new_src, outcomes_js)


# Settings (#90): the sections region between the comment sentinels. Sentinel-anchored
# rather than </div>-counted, so wrapping the section list in a container can't silently
# break the splice the way _OUTCOMES_LIST_RE can.
_SETTINGS_SECTIONS_RE = re.compile(
    r"(<!-- SETTINGS SECTIONS -->)(.*?)(<!-- /SETTINGS SECTIONS -->)", re.DOTALL
)


def _set_field(label: str, name: str, value: str, *, placeholder: str = "",
               hint: str = "", type_: str = "text", textarea: bool = False) -> str:
    ph = f' placeholder="{html.escape(placeholder)}"' if placeholder else ""
    if textarea:
        field = f'<textarea class="set-input" name="{name}"{ph}>{value}</textarea>'
    else:
        field = f'<input class="set-input" type="{type_}" name="{name}" value="{value}"{ph}>'
    hint_html = f'<div class="set-hint">{html.escape(hint)}</div>' if hint else ""
    return f'<label class="set-label">{html.escape(label)}</label>{field}{hint_html}'


def _set_select(label: str, name: str, value: str, choices: tuple, hint: str = "") -> str:
    opts = "".join(
        f'<option value="{html.escape(v)}"{" selected" if v == value else ""}>{html.escape(t)}</option>'
        for v, t in choices
    )
    hint_html = f'<div class="set-hint">{html.escape(hint)}</div>' if hint else ""
    return (f'<label class="set-label">{html.escape(label)}</label>'
            f'<select class="set-input" name="{name}">{opts}</select>{hint_html}')


def _set_checkbox(label: str, name: str, checked: bool) -> str:
    return (f'<label class="set-label"><input type="checkbox" name="{name}" value="1"'
            f'{" checked" if checked else ""} style="width:auto;margin-right:7px;vertical-align:-1px">'
            f'{html.escape(label)}</label>')


def _account_news_status_html(db: Any, cfg: dict) -> str:
    """Account-level news status. The key is reported as a boolean and nothing more:
    never the value, never a prefix, never its length."""
    from pmqs import repository, settings as settings_mod

    key_ok = bool(settings_mod.resolve_brave_key(db))
    last_run = cfg.get("last_run") or ""
    rows = [
        f'Brave key: <b>{"resolves" if key_ok else "not found"}</b>',
        f'Last run: <b>{html.escape(last_run.replace("T", " ")) if last_run else "never"}</b>'
        + (f' \u00b7 promoted <b>{cfg.get("last_promoted", 0)}</b> across all products' if last_run else ""),
        f'Items in store: <b>{len(repository.list_news_items(db))}</b>',
        'Fetched by <b>Refresh</b> on the Inbox, alongside repo triggers.',
    ]
    return f'<div class="set-status">{"<br>".join(rows)}</div>'


def _product_news_status_html(db: Any, product: Any) -> str:
    """What this product will actually search, and what it has collected."""
    from pmqs import repository, settings as settings_mod

    queries = settings_mod.effective_news_queries(db, product)
    stored = len(repository.list_news_items(db, product_id=product.id))
    rows = [
        f'Queries this run: <b>{len(queries)}</b>',
        f'Items collected for this product: <b>{stored}</b>',
    ]
    preview = ""
    if queries:
        items = "".join(f"<div>{html.escape(q)}</div>" for q in queries)
        preview = f'<div class="set-label">Will search</div><div class="set-status">{items}</div>'
    return f'<div class="set-status">{"<br>".join(rows)}</div>{preview}'


def _settings_sections(db: Any, prefix: str = "") -> str:
    """ACCOUNT sections. The API key is NEVER echoed back: shown masked.

    The watchlist, product profile and lens weights are NOT here -- they belong to a
    Product and live in _product_settings_sections (#98).
    """
    from pmqs import members as members_repo
    from pmqs import settings as settings_mod
    from pmqs.models import Member

    cfg = settings_mod.get_llm(db)
    key_display = "\u2022" * 8 + " (stored)" if cfg.get("api_key_raw") else html.escape(cfg.get("api_key_ref") or "")
    news = settings_mod.get_news_config(db)
    n_key_display = "\u2022" * 8 + " (stored)" if news.get("api_key_raw") else html.escape(news.get("api_key_ref") or "")

    member = db.get(Member, members_repo.current_member_id(db))
    display_name = html.escape(member.display_name if member else "")

    you = f"""<form method="post" action="/settings">
<div class="set-section"><h2>You</h2>
<div class="set-scope">Your name, your model, your key. Applies to every product.</div>
{_set_field("Display name", "display_name", display_name, placeholder="You",
            hint="Shown in the left rail and against every outcome you produce.")}
{_set_field("Provider", "provider", html.escape(cfg.get("provider", "")), placeholder="anthropic")}
{_set_field("Model", "model", html.escape(cfg.get("model", "")), placeholder="anthropic/claude-haiku-4-5-20251001")}
{_set_field("API key env var (recommended)", "api_key_ref", key_display, placeholder="ANTHROPIC_API_KEY",
            hint="Reference an environment variable rather than pasting a key. The key is never displayed once stored.")}
{_set_field("API key (optional, inline \u2014 stored, never shown)", "api_key_raw", "", type_="password",
            placeholder="leave blank to keep current")}
{_set_field("Base URL (optional, for OpenAI-compatible endpoints)", "base_url", html.escape(cfg.get("base_url", "")))}
<button class="set-btn" type="submit">Save</button>
</div></form>"""

    news_section = f"""<form method="post" action="/settings/news">
<div class="set-section"><h2>News</h2>
<div class="set-scope">Your Brave key and throttles. Each product's watchlist lives in that product's settings.</div>
{_set_checkbox("Ingest news", "news_enabled", news.get("enabled", True))}
{_set_field("Brave API key env var", "news_api_key_ref", n_key_display, placeholder="BRAVE_API_KEY",
            hint="Stored as an env-var reference or inline (masked, never shown). Never committed to the repo.")}
{_set_field("Brave API key (optional, inline \u2014 stored, never shown)", "news_api_key_raw", "", type_="password",
            placeholder="leave blank to keep current")}
<div class="set-row">
<div>{_set_select("Freshness", "freshness", str(news.get("freshness", "pw")), settings_mod.FRESHNESS_CHOICES)}</div>
<div>{_set_field("Results per query", "count", html.escape(str(news.get("count", 10))))}</div>
</div>
<div class="set-row">
<div>{_set_field("Max questions per product per run", "top_n", html.escape(str(news.get("top_n", 3))))}</div>
<div>{_set_field("Relevance threshold (0\u20131)", "min_relevance", html.escape(str(news.get("min_relevance", 0.5))))}</div>
</div>
{_account_news_status_html(db, news)}
<button class="set-btn" type="submit">Save</button>
</div></form>"""

    advanced = f"""<form method="post" action="/settings/advanced">
<div class="set-section"><h2>Advanced</h2>
<div class="set-scope">Rarely needs changing.</div>
{_set_field("Context feed budget (characters)", "char_budget",
            html.escape(str(settings_mod.get_context_budget(db))),
            hint="Cap on the durable-outcome context block assembled for agents.")}
<button class="set-btn" type="submit">Save</button>
</div></form>"""

    return "\n".join([you, news_section, advanced])


def render_settings(db: Any, template_path: Path | None = None, *,
                    workspace_slug: str | None = None) -> str:
    """ACCOUNT settings, spliced into the template's Settings view.

    Account-wide, so it takes no product and is reached at an UNPREFIXED /settings from
    the identity block. `workspace_slug` survives only so the rail can keep its Product
    switcher pointed somewhere sensible; it scopes nothing. Product settings is a
    different page -- see render_product_settings (#98).

    The API key is NEVER echoed back: shown masked. See _settings_sections.
    """
    return _render_settings_view(
        db, _settings_sections(db), template_path=template_path, workspace_slug=workspace_slug
    )


_PRODUCT_FLASHES = {
    "invalid_repo": ("error", "That doesn't look like a repository. Paste the GitHub URL or type org/repo (e.g. open-agentos/agentos-pmqs). Your other fields are kept below."),
    "added": ("ok", "Product added. Give it a watchlist and a profile and it'll start earning its inbox."),
}


def _product_flash_html(flash: str | None) -> str:
    """Render the flag instead of swallowing it. `?product_error=invalid_repo` has been
    redirected to since #53 and rendered by NOTHING -- type a bad ref and you were
    silently bounced with no explanation (#99)."""
    if not flash or flash not in _PRODUCT_FLASHES:
        return ""
    kind, message = _PRODUCT_FLASHES[flash]
    colour = "--pulse-coral" if kind == "error" else "--accent-sage"
    return (f'<div class="set-section" style="border-color:var({colour})">'
            f'<div style="color:var({colour});font-size:13px">{html.escape(message)}</div></div>')


def _research_button_html() -> str:
    """The 'Research this site' control. type=button so it never submits the form; the
    LLM/search spend happens only on this explicit click (decision 12.2)."""
    return (
        '<div class="set-row" style="align-items:center;gap:10px">'
        '<button class="set-btn" type="button" onclick="pmqsResearchSite(this)">Research this site</button>'
        '<span class="research-status" role="status" style="color:var(--text-muted);font-size:13px"></span>'
        '</div>'
    )


# Client-side prefill: POST the website to /products/research, drop the returned draft
# into the form's fields for review. Only overwrites a field when a value came back, so
# a thin result never blanks something the PM typed. Shared by create and edit forms.
_RESEARCH_JS = """
<script>
async function pmqsResearchSite(btn){
  var form = btn.closest('form'); if(!form) return;
  var urlEl = form.querySelector('[name="website"]');
  var url = urlEl ? urlEl.value.trim() : '';
  var status = form.querySelector('.research-status');
  if(!url){ if(status) status.textContent = 'Enter a website first.'; return; }
  btn.disabled = true; if(status) status.textContent = 'Researching\\u2026';
  var map = {display_name:'name', product_profile:'profile', wl_industry:'industry',
             wl_keywords:'keywords', wl_companies:'companies', wl_products:'products',
             wl_sources:'sources'};
  try{
    var resp = await fetch('/products/research', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({url:url})});
    var data = resp.ok ? await resp.json() : null;
    if(data && !data.error){
      var filled = 0;
      Object.keys(map).forEach(function(f){
        var el = form.querySelector('[name="'+f+'"]'); var v = data[map[f]];
        if(el && v){ el.value = v; filled++; }
      });
      if(status) status.textContent = filled
        ? 'Filled in below \\u2014 review and edit.'
        : "Couldn't find much \\u2014 fill in what you can.";
    } else if(status){ status.textContent = "Couldn't research that site \\u2014 fill in what you can."; }
  }catch(e){ if(status) status.textContent = "Couldn't reach the research service."; }
  finally{ btn.disabled = false; }
}
</script>
"""


def _product_settings_sections(db: Any, product: Any, prefix: str, mode: str = "edit",
                               flash: str | None = None, values: Any = None) -> str:
    """PRODUCT sections: what makes this product this product.

    `mode="create"` renders the same fields with an empty Product and a Create button --
    Add Product is this view before the Product exists (#99). `values` repopulates those
    fields after a failed submit so reviewed content survives a validation error.
    """
    from pmqs import config
    from pmqs import members as members_repo
    from pmqs import products as products_repo

    creating = mode == "create"
    news = products_repo.get_news_config(db, product)
    wl = news.get("watchlist") or {}

    def _wl(field: str) -> str:
        return html.escape("\n".join(wl.get(field) or []))

    def fv(name: str, fallback: str = "") -> str:
        """Field value: on a create re-render after error, echo what was submitted;
        otherwise use the normal fallback (empty for create, stored for edit)."""
        if creating and values is not None:
            return html.escape(str(values.get(name, "")))
        return fallback

    action = "/products" if creating else f"{prefix}/settings"
    verb = "Add product" if creating else "Save"
    label = "" if creating else html.escape(products_repo.product_display_name(db, product))

    if creating:
        identity = f"""<div class="set-section"><h2>Add a product</h2>
<div class="set-scope">Give it a website and let PMQs draft the details, or just fill them in. Everything can be changed later.</div>
{_set_field("Website", "website", fv("website"), placeholder="https://yourproduct.com",
            hint="The product or company home page. We'll read it and pre-fill the fields below \u2014 review before you save.")}
{_research_button_html()}
{_set_field("Repository", "repo", fv("repo"), placeholder="org/repo",
            hint="Paste the GitHub URL or type org/repo. Resolves to the existing product if a colleague already added this repo.")}
{_set_field("Display name", "display_name", fv("display_name"), placeholder="what it's called")}
{_set_field("Nickname (optional)", "nickname", fv("nickname"), placeholder="what you call it",
            hint="Shown in the switcher. Sets the URL when the product is created.")}
</div>"""
    else:
        identity = f"""<div class="set-section"><h2>{label}</h2>
<div class="set-scope">This product only.</div>
{_set_field("Website", "website", html.escape(news.get("website", "")),
            placeholder="https://yourproduct.com",
            hint="The home page research runs against. Re-research to refresh the watchlist below.")}
{_research_button_html()}
{_set_field("Display name", "display_name", html.escape(product.display_name or ""))}
{_set_field("Nickname (optional)", "nickname", html.escape(product.nickname or ""),
            placeholder="what you call it",
            hint=f"Shown in the switcher. The URL stays /w/{product.slug}/ \u2014 it's set when the "
                 "product is created and doesn't move when you rename.")}
{_set_field("Repository", "repo", html.escape(product.full_name), placeholder="org/repo")}
</div>"""

    watchlist = f"""<div class="set-section"><h2>Watchlist</h2>
<div class="set-scope">What this product watches for. One per line; everything except sources becomes a search, sources restrict all of them.</div>
{_set_field("Industry", "wl_industry", fv("wl_industry", _wl("industry")), textarea=True, placeholder="agent orchestration")}
{_set_field("Keywords", "wl_keywords", fv("wl_keywords", _wl("keywords")), textarea=True, placeholder="AI product management")}
{_set_field("Companies", "wl_companies", fv("wl_companies", _wl("companies")), textarea=True, placeholder="Anthropic")}
{_set_field("Product names", "wl_products", fv("wl_products", _wl("products")), textarea=True, placeholder="Claude Code")}
{_set_field("Media sources", "wl_sources", fv("wl_sources", _wl("sources")), textarea=True, placeholder="techcrunch.com",
            hint="Domains. Folded into every search as one site: group, not searched on their own.")}
{_set_field("Raw queries (advanced, one per line)", "news_queries",
            fv("news_queries", html.escape("\n".join(news.get("queries", [])))), textarea=True,
            hint="Brave query syntax, passed through untouched and appended to the composed ones.")}
{_set_field("Product profile (what the relevance pass judges against)", "product_profile",
            fv("product_profile", html.escape(news.get("product_profile", ""))), textarea=True,
            placeholder="What the product is, who competes, what the PM cares about\u2026")}
{"" if creating else _product_news_status_html(db, product)}
</div>"""

    weights = products_repo.weights_for(db, None if creating else product.id)
    rows = "".join(
        f'<div>{_set_field(config.LENS_LABELS[k], f"lens_{k}", fv(f"lens_{k}", html.escape(str(weights[k]))))}</div>'
        for k in config.LENS_WEIGHTS
    )
    lenses = f"""<div class="set-section"><h2>Lens weights</h2>
<div class="set-scope">How much each of the 8 lenses matters for this product. Defaults are sane; tune only what's wrong.</div>
<div class="set-row">{rows}</div>
</div>"""

    body = f"""<form method="post" action="{action}">
{identity}
{watchlist}
{lenses}
<div class="set-section"><button class="set-btn" type="submit">{verb}</button></div>
</form>"""

    if creating:
        return _product_flash_html(flash) + body + _RESEARCH_JS

    people = members_repo.list_product_members(db, product_id=product.id)
    member_rows = "".join(
        f'<div>{html.escape(m.display_name or "You")} <span style="color:var(--text-muted)">\u00b7 {html.escape(role)}</span></div>'
        for m, role in people
    ) or '<div style="color:var(--text-muted)">No members recorded.</div>'
    members_section = f"""<div class="set-section"><h2>Members</h2>
<div class="set-scope">Everyone attached to this product. Invites aren't built yet.</div>
<div class="set-status">{member_rows}</div>
</div>"""

    archive = f"""<form method="post" action="{prefix}/settings/archive">
<div class="set-section"><h2>Archive</h2>
<div class="set-scope">Hides this product from the switcher. Nothing is deleted.</div>
<button class="set-btn" type="submit">Archive this product</button>
</div></form>"""

    return "\n".join([_product_flash_html(flash), body, members_section, archive, _RESEARCH_JS])


def render_product_settings(db: Any, product: Any, template_path: Path | None = None, *,
                            workspace_slug: str | None = None, mode: str = "edit",
                            flash: str | None = None, values: Any = None) -> str:
    """PRODUCT settings. Reached at /w/{slug}/settings from the Product switcher.

    Shares the template's Settings view slot with render_settings -- one view, two
    renderers, because the shell is identical and only the sections differ.

    `values` (a form mapping) repopulates the create form after a validation error, so a
    bad repo ref doesn't throw away the researched/reviewed fields the PM just filled in.
    """
    prefix = f"/w/{workspace_slug}" if workspace_slug else ""
    return _render_settings_view(
        db, _product_settings_sections(db, product, prefix, mode, flash, values),
        template_path=template_path, workspace_slug=workspace_slug,
    )


def _render_settings_view(db: Any, sections: str, *, template_path: Path | None = None,
                          workspace_slug: str | None = None) -> str:
    src = _load_template(template_path)
    src = _apply_rail(src, db, workspace_slug)
    new_src, n = _SETTINGS_SECTIONS_RE.subn(lambda m: f"{m.group(1)}\n{sections}\n{m.group(3)}", src)
    if n == 0:
        raise RuntimeError("Could not locate Settings sections region in app template")
    _prefix = f"/w/{workspace_slug}" if workspace_slug else ""
    settings_js = _live_js_common(_prefix) + """
<script>
document.addEventListener('DOMContentLoaded', function(){
  if (typeof showView === 'function') showView('settings');
});
</script>
"""
    return _inject_before_body_close(new_src, settings_js)
