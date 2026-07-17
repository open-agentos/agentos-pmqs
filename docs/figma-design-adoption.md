# Applying the Figma design exploration to PMQs — build spec

**Repo:** `open-agentos/agentos-pmqs`
**Scope:** structure and interaction only. **No brand change.**
**Suggested model:** Claude Sonnet, one issue per run.

---

## 0. Read this first

A Figma Make exploration (React/Vite/Tailwind) was produced as a design study. It is
**not** being ported. It is a source of design decisions, three of which are better than
what is shipped. This spec is the only thing you should build from — you do not need the
Figma files.

**Two hard constraints. Violating either fails review.**

1. **Do not touch the palette, fonts, or any colour token.** The Figma study uses a warm
   cream canvas, a violet accent, and Fraunces/Plus Jakarta. That is a different brand.
   PMQs is dark (`--bg-main:#12181c`) with teal/gold/sage/cyan/coral, and violet was
   deliberately removed from the palette in #26. Every new element must be built from
   tokens **already defined** in `app.html`'s `:root`. `tests/test_brand_doc.py` asserts
   every colour token in the template appears in `docs/brand-design-system.md` §3 with a
   matching value — introducing one hex literal turns CI red. A brand pivot is a separate
   decision that has been explicitly deferred; do not anticipate it.

2. **Read `pmqs/pmqs/web/TEMPLATE-CONTRACT.md` in full before editing `app.html`.**
   `app.html` is the app's only template. `render.py` splices real data into it with
   **regex matched against its markup**, including literal `</div>` counts. No test
   asserts on any of it. A broken splice does not fail CI — it serves a page with fixture
   data silently left in place. Two of the three Wave 1 items sit directly on top of an
   anchor.

**Repo conventions:** branch `agent/builder/{issue}-{slug}`; PR `base=main` with a
non-empty `closingIssuesReferences`; smallest change that satisfies the issue; no
unrelated refactors.

---

## Wave 1

### Issue 1 — Two-pane Inbox

**Why.** Today a card click leaves the Inbox entirely and opens a Workspace — a full
context switch to triage one item. The email-client model (list column + detail pane)
lets you read the question, check its evidence, and act without leaving. This is the
single biggest win in the study.

**Build.**

- Split `#view-inbox` into a fixed-width list column and a flexible detail pane. Keep
  `.inbox-header`, `.filter-bar` and `.quick-add` in the list column, in that order.
- The detail pane renders the selected question:
  - **Source card** — evidence ref, `.pill` lens tags, age. Reuse `--bg-surface` +
    `--border-default`. Build it so Issue 5 can extract it.
  - **Context** — the question's `description`.
  - **Actions** — "Open workspace" (primary, `--accent-gold`), Save, Dismiss. These call
    the existing `pmqsOpenWorkspace(qid)` / `pmqsSetStatus(qid, …)`.
- Selecting a card sets an active state on the row (left border, `--accent-teal-dim`) and
  swaps the detail pane. First card selected on load. Empty state when the list is empty.
- Clicking a `.card` now **selects** rather than navigates. The `⚔` icon-btn keeps its
  current navigate-to-workspace behaviour, so the old path stays reachable.

**⚠ The anchor.** `_CARDS_REGION_RE` (render.py:193) matches:

```
(<div class="quick-add">.*?</div>\s*)(.*?)(\s*</div>\s*</div>\s*<!-- WORKSPACE VIEW -->)
```

Group 3 counts on the card list being followed by exactly two `</div>`s and then the
`<!-- WORKSPACE VIEW -->` comment. **Adding a detail pane as a sibling breaks this even
though nothing is renamed.**

Fix it the way TEMPLATE-CONTRACT §6/§7 tells you to — replace the `</div>` counting with
sentinels, in the same commit:

1. Wrap the card list in `<!-- INBOX CARDS -->` … `<!-- /INBOX CARDS -->` in `app.html`.
2. Rewrite `_CARDS_REGION_RE` to anchor on those sentinels.
3. Update TEMPLATE-CONTRACT.md §1 and §2.

Leave `<!-- WORKSPACE VIEW -->` in place — the contract lists it as load-bearing and other
readers rely on the symmetry.

**Data.** `GET /api/questions` (`api/inbox.py:128`) already returns `id`, `title`,
`status`, `source`, `lens_tags`, `score`, `score_dims`, `evidence`. Add `description` and
`created_at` to that response — the detail pane needs both. No new endpoint.

**Do not** hydrate the detail pane by re-rendering server-side per selection. Ship the
question list as JSON alongside the rendered cards and switch client-side.

**Done when:** `/` renders two panes with real data; selecting a card swaps the detail
pane without a navigation; filter pills still filter; quick-add still adds; the `⚔`
button still opens the workspace; `docs/` updated. New test asserts the spliced Inbox
contains real question titles and that both sentinels survive.

---

### Issue 2 — Restyle the artifact tab bar and the for/against grid

**Why.** Two treatments from the study, both pure CSS on existing markup.

**Build.**

- **Tab bar** (`data-tab` = `doc` | `chart` | `evidence` | `proposed`): underline the
  active tab in `--accent-gold` rather than the current treatment, and put the item count
  in the label — `Evidence (4)`, `Proposed (2)`. Counts come from the length of what
  `render.py` already splices into each pane; render `(0)` when empty rather than hiding.
- **For/against grid**: restyle `.doc-grid` / `.doc-box.for` / `.doc-box.against` as the
  study's two-column card — `+` markers on the for side in `--accent-sage`, `−` markers on
  the against side in `--pulse-coral`, coloured section labels, more generous padding.

**⚠ Keep the tab pane `id`s and their order.** `_TAB_DOC_RE`, `_TAB_EVID_RE` and
`_TAB_PROP_RE` anchor on `<div id="tab-doc">` … `<div id="tab-chart"` and friends.
`_TAB_PROP_RE` ends on **four literal `</div>`s** — wrapping the artifact pane in one
extra container div breaks the splice with nothing renamed. Restyle with CSS. Do not
re-nest.

**Not in scope.** The study also has lettered "Option A/B/C" cards with risk and effort
tags. PMQs has no options model — the position document is for/against on a single
question. Do not invent one. The `+`/`−` treatment above is what carries over.

**Also not in scope.** Rebuttals already render (`rebuttal_for` / `rebuttal_against` in
`_position_doc_html`). Leave them; just make sure they read cleanly inside the new box.

**Done when:** all four tabs still splice real data — verify by loading a real workspace
in a browser, not just by running pytest; `tests/test_render_workspace.py` and
`test_position_doc.py` stay green; no new colour token.

---

### Issue 3 — Thread-line treatment on the conversation pane

**Why.** `.convo-scroll` is a flat stack of `.msg` blocks. The study's avatar + connecting
vertical line reads as a conversation, which is what the Workspace is meant to be.

**Build.** Add an initials avatar and a vertical connector between consecutive messages,
using `--border-default` for the line and `--accent-teal` / `--accent-teal-fg` for the
avatar. Suppress the connector on the last message.

**⚠ The anchor.** `_CONVO_RE` matches `<div class="convo-scroll">` … `<div
class="convo-input">`. Both class names and their order are load-bearing. `render.py`
emits `.msg`, `.msg-label`, `.msg-body`, `.sys-bubble` — every one must keep a CSS rule or
real messages render unstyled. Add the avatar **inside** the existing `.msg` structure, or
adjust `_msg_html` in `render.py` and the template together in one commit.

**Done when:** a real workspace conversation renders with avatars and connectors;
`test_render_workspace.py` green; no new colour token.

---

## Wave 2

### Issue 4 — Rank badge on Inbox rows

The Inbox claims a ranked list; ordering is currently the only tell. Add a small mono rank
badge (`--font-mono`, `--text-muted`) to the left of each `.card-title`, emitted from
`question_card_html()`. Top two get `--accent-gold-dim`. Rank is the row's index in the
already-sorted list — do not recompute scores. Keep the existing `score N.NN` pill; the
badge is position, the pill is magnitude.

**Preserve the scoring model.** The study collapses everything to
critical/high/medium/low. PMQs has multi-dimensional `score_dims` plus the Urgent /
Asked-by-you / System-raised / Saved axis. Do not replace it with a four-level severity
enum.

**⚠** `.card`, `.card-main`, `.card-title`, `.card-meta`, `.card-actions`, `.card-age` are
all emitted by `render.py` (§4 of the contract). The badge is a new element inside
`.card-main` — add it in `question_card_html()` and give it a CSS rule.

### Issue 5 — Extract the source card as a shared partial

Issue 1 builds a source card in the Inbox detail pane. The Evidence tab renders the same
object with different markup (`.evidence-item` / `.evidence-title` / `.evidence-sub`).
Pull one builder in `render.py` that both call. Keep `.evidence-*` class names — they are
in the contract. Pure refactor; no visual change to the Evidence tab.

---

## Explicitly out of scope

Do not implement these even though the study shows them, and do not "fix" the app to match:

| Study shows | Reality |
|---|---|
| Static repo block in the rail | The product switcher shipped in #51–#57. Keep it. |
| `War Room` as a nav label | The name is **Workspaces**. Keep it. |
| No workspaces list | `#view-workspaces` is a deliberate decision. Keep it. |
| "Record a decision" free-text | The five outcome types (issue / policy / document / meeting / question) are the product thesis. Keep the outcome bar. |
| Discussion / Options / Related tabs | The four artifact tabs stay. |
| No quick-add | Keep it. |
| No session indicator | Keep `.session-stats` — `_STATS_RE` anchors on it. |
| critical / high / medium / low | Keep the scoring model. |
| Cream + violet + Fraunces | **Deferred brand decision. Do not touch tokens.** |

---

## Verification, every issue

`python -m pytest` is **necessary but not sufficient** — the suite passes with the
template's markup arbitrarily broken. For any issue that touches `app.html` or
`render.py`, also load `/`, a real workspace, `/outcomes` and `/settings` in a browser and
confirm **real data appears rather than fixture content**. A page showing "acme-app" or
"Ship a mitigation now, or keep blocking on…" is a failed splice, not a passing build.

If you change an anchor, change both sides in one commit and update
`TEMPLATE-CONTRACT.md`. Prefer sentinels over `</div>` counting for anything new.
