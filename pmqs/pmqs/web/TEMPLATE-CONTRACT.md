# Template contract — `templates/app.html`

**Read this before restyling `app.html`.**

`app.html` is not a mockup and not a reference. It is the app's only HTML template.
`render.py` reads it at request time and splices real data into it using **anchored
regular expressions matched against its markup**. Every page PMQs serves is this file
with fixture content replaced.

That makes a specific subset of the markup a **load-bearing API**:

| Free to change | Load-bearing — do not change without updating `render.py` |
|---|---|
| Colours, tokens, hex values | Class names listed below |
| Fonts, sizes, weights, tracking | `id` attributes listed below |
| Spacing, padding, radii, shadows | `data-*` attributes listed below |
| Borders, backgrounds, transitions | HTML comment sentinels listed below |
| Adding **new** elements/classes | DOM nesting depth at the anchor points |
| Copy and labels | Tag types at the anchor points (`div` vs `span`) |

**No test asserts on any of this.** The suite passes with the template's markup
arbitrarily broken. Breakage surfaces as a `RuntimeError` at request time, or worse,
as a page that renders with fixture data silently left in place. CI will not catch it.

---

## 1. Regex anchors

Each of these is a `re.compile` in `render.py`. The **first and third capture groups
are matched literally** — the middle group is what gets replaced. If the literal text
in groups 1 and 3 stops matching, the splice fails.

| Constant | Anchors on | Breaks if you… |
|---|---|---|
| `_CARDS_REGION_RE` | `<!-- INBOX CARDS -->` … `<!-- /INBOX CARDS -->` | delete either sentinel |
| `_WS_TITLE_RE` | `<span class="ws-title">` | rename `.ws-title` or change it from a `<span>` |
| `_CONVO_RE` | `<div class="convo-scroll">` … `<div class="convo-input">` | rename either class, or reorder them |
| `_TAB_DOC_RE` | `<div id="tab-doc">` … `<div id="tab-chart"` | rename either `id`, or reorder the tab panes |
| `_TAB_EVID_RE` | `<div id="tab-evidence">` … `<div id="tab-proposed"` | as above |
| `_TAB_PROP_RE` | `<div id="tab-proposed">` … 4 closing `</div>`s | as above, **or change nesting depth after the last tab** |
| `_STATS_RE` | `<span class="session-stats">` | rename `.session-stats` or change its tag |
| `_tab_label_re(t)` | `data-tab="{t}"` … `</div>` | change a tab from a `<div>`, or put markup inside a tab label (#108 writes the item count into it as plain text) |
| `_OUTCOMES_LIST_RE` | `<div id="outcomes-list">` … 5 closing `</div>`s | rename the `id`, **or change nesting depth after the ledger** |
| `_SUM_RE_TMPL` | `<div class="summary-num" id="sum-{type}">` | rename `.summary-num`, or change the `sum-*` id scheme |
| `_SETTINGS_SECTIONS_RE` | `<!-- SETTINGS SECTIONS -->` … `<!-- /SETTINGS SECTIONS -->` | delete either sentinel |
| `_IDENTITY_RE` | `<!-- IDENTITY -->` … `<!-- /IDENTITY -->` | delete either sentinel |
| `_PS_SETTINGS_RE` | `<a class="ps-item" id="ps-settings" href="…">` | rename the id, or reorder the class/id attributes |

⚠️ **The closing-`</div>` counts in `_TAB_PROP_RE` and `_OUTCOMES_LIST_RE` are
literal.** Wrapping the artifact pane or the ledger in one extra container div breaks
them, even though nothing was renamed. This is the most likely accidental break during
a restyle.

⚠️ **`_OUTCOMES_LIST_RE`'s five `</div>`s reach past the Outcomes view to the closes of
`#main` and `#app`.** So `#view-outcomes` must stay the **last child of `#main`** — adding
any sibling view after it breaks the Outcomes render with nothing renamed and nothing
re-wrapped. This is why `<!-- SETTINGS VIEW -->` sits *above* `<!-- OUTCOMES VIEW -->`
rather than at the end where it reads more naturally. DOM order is cosmetic here:
`.view` is `position:absolute` and toggled by `showView()`.

`_SETTINGS_SECTIONS_RE` and `_CARDS_REGION_RE` are sentinel-anchored precisely to avoid
joining this club. Prefer sentinels over `</div>` counting for anything new.

`_CARDS_REGION_RE` earned its way out the hard way (#107). It used to run from
`<div class="quick-add">` to `</div></div><!-- WORKSPACE VIEW -->`, so its middle group
was *everything in between* — and because `#view-workspaces` was later added between the
Inbox and that comment, rendering the Inbox quietly deleted the entire Workspaces list
view from the page. Nothing was renamed, nothing was re-wrapped, no test failed, and the
only reason it never surfaced is that `/workspaces` is a separate render off a clean
template. That is exactly the failure mode this document warns about, and it shipped
anyway. `tests/test_inbox_two_pane.py::test_splice_stays_inside_the_sentinels` now
pins it.

### `sum-*` ids required by the summary strip

`sum-issue`, `sum-policy`, `sum-document`, `sum-meeting`, `sum-question`

---

## 2. Comment sentinels

These HTML comments are **structural markers, not documentation.** Do not tidy them away.

| Comment | Status |
|---|---|
| `<!-- INBOX CARDS -->` / `<!-- /INBOX CARDS -->` | **load-bearing** — `_CARDS_REGION_RE` |
| `<!-- WORKSPACE VIEW -->` | no longer matched (was `_CARDS_REGION_RE`, until #107); keep for symmetry |
| `<!-- LOGO MARK -->` | **load-bearing** — `_load_template()` replaces it with the mark from `logo.py`. Delete it and the logo silently disappears. |
| `<!-- INBOX VIEW -->` | not currently matched; keep for symmetry |
| `<!-- OUTCOMES VIEW -->` | not currently matched; keep for symmetry |
| `<!-- SETTINGS SECTIONS -->` / `<!-- /SETTINGS SECTIONS -->` | **load-bearing** — `_SETTINGS_SECTIONS_RE` |
| `<!-- IDENTITY -->` / `<!-- /IDENTITY -->` | **load-bearing** — `_IDENTITY_RE` |
| `<!-- LEFT RAIL -->` | not currently matched; keep for symmetry |
| `<!-- MAIN -->` | not currently matched; keep for symmetry |

A reader cannot tell which of these are matched by looking, and the set changes.
Treat all of them as load-bearing.

---

## 3. Selectors bound by injected JavaScript

`render.py` injects `<script>` blocks that override the template's demo handlers with
real backend calls. They bind to:

| Selector | Purpose |
|---|---|
| `.nav-item[data-nav="inbox"]` | routes to `/` |
| `.nav-item[data-nav="outcomes"]` | routes to `/outcomes` |
| `.nav-item[data-nav="workspace"]` | routes to `/workspaces` |
| `.filter-pill` | Inbox filtering |
| `#inbox-detail` | Inbox detail pane; `pmqsSelect()` swaps its `innerHTML` (#107) |
| `#pmqs-question-detail` | JSON blob of pre-rendered detail HTML, keyed by question id (#107) |
| `.card[data-qid]` | Inbox selection; `data-qid` is the key into that blob |
| `#quick-add-input` | quick-add question |
| `#chat-input` | war-room message |
| `#identity-block` | Account Settings link. Always `/settings`, never prefixed — account settings scopes to no product |
| `#ps-settings` | Product Settings link; `href` spliced to the current product |

The `data-nav` attribute values (`inbox`, `workspace`, `outcomes`) are part of the contract.
So are `data-tab` (`doc`, `chart`, `evidence`, `proposed`) and `data-type`.

---

## 4. Classes `render.py` emits

`render.py` generates markup using these classes. The template must keep a CSS rule for
each, or real data renders unstyled — a failure that looks like a design bug, not a
wiring bug:

```
card  card-main  card-title  card-meta  card-actions  card-age  selected  rank-badge
icon-btn  primary  pill  quick-add
inbox-list  inbox-detail  detail-empty  detail-title  detail-section  detail-label
detail-body  detail-actions  d-btn  source-card  source-ref  source-meta
convo-scroll  convo-input  msg  msg-label  msg-body  sys-bubble  pm-bubble
msg-avatar  msg-col
ws-title  session-stats
doc  doc-sub  doc-section  doc-label  doc-text  doc-grid  doc-box
evidence-item  evidence-title  evidence-sub
proposed-item  proposed-title  proposed-actions  p-add
ledger-item  ledger-main  ledger-src  ledger-time
summary-num  inbox-header  for  against  system
set-section  set-scope  set-label  set-input  set-hint  set-row  set-btn
```

Card variant classes (`.card.saved`, `.card.asked`, `.card.system`, `.card.news`) are
chosen in `question_card_html()` and must keep working as modifiers on `.card`.

---

## 5. The logo mark

`templates/app.html` does **not** contain the mark. It contains a placeholder:

```html
<span class="logo-mark"><!-- LOGO MARK --></span>
```

`_load_template()` replaces that sentinel with the SVG from `logo.py`, which reads
`assets/logo-mark.svg`. Every render path loads through `_load_template()`, so the splice
happens in exactly one place.

**Why it isn't just inline in the template:** `render_error()` builds its own standalone
document, and #28 needs the same mark as a favicon. Inline would mean three copies and
inevitable drift. (`render_settings()` used to be the third such document; as of #90 it
renders through the template like every other view.)

**To change the mark, edit `assets/logo-mark.svg` and nothing else.** That file carries
the design brief for §2's open per-facet bevel work.

Consequence worth knowing: opening `app.html` directly in a browser shows the wordmark
without the mark. That's expected — the file still opens and still renders, it just isn't
the whole lockup outside the app.

Classes `.logo-lockup`, `.logo-mark` and `.logo-text` are structural: `logo.py`'s
`lockup_html()` and the template's rail markup both assume them.

## 6. If you need to change an anchor

Fine — it's not frozen forever, just coupled. Change both sides in the same commit:

1. Update the markup in `app.html`
2. Update the matching constant or selector in `render.py`
3. Run `python -m pytest` — necessary, **not sufficient**; it will pass either way
4. Actually load `/`, `/workspace`, `/outcomes` and `/settings` in a browser and
   confirm real data appears rather than fixtures
5. Update this document

## 7. Known follow-on

`jinja2` is already a declared dependency in `pyproject.toml` and is entirely unused.
Replacing the regex splices with real templating would make this contract *enforceable*
rather than *advisory*, and would delete most of this document. That is the right
long-term fix. Until then, this file is the only thing standing between a restyle and a
silently broken render.
