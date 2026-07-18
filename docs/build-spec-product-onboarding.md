# PMQs: Product Onboarding Research — Implementation Plan

**Status:** Draft 1 — handoff spec
**Audience:** an AI coding agent (or Matt) picking this up cold, with no access to the conversation that produced it
**Repo:** `agentos-pmqs`
**Prerequisite:** the Settings / Add Product waves are merged (`api/products.py::add_product`, `web/render.py::_product_settings_sections`, `api/settings.py::save_product_settings` all present on `main`)

---

## 0. How to use this document

Sections 1–3 are the *why* and the *shape*. Section 4 is where it plugs into the existing code — read it against the actual files before writing anything. Section 5 is the research pipeline. Section 6 is storage. Section 7 is the gap that has to close first or the feature does nothing. Section 8 is the work, in reviewable units with acceptance criteria. Section 9 is behaviour and cost bounds. **Section 10 is repo traps that have already cost this project real time — read it before opening a PR.** Section 11 is out of scope. Section 12 needs a human (Matt).

Where this doc and the code disagree, **the code wins** — flag it rather than forcing the doc's shape.

---

## 1. What this feature is

Adding a product to PMQs today means typing an `org/repo` and then facing a set of empty boxes — watchlist (industry, keywords, companies, product names, media sources), a product profile, and lens weights. Those boxes are what make a product *useful* (they drive news ingestion, relevance scoring, and question generation), and they are exactly the thing a new user is least equipped to fill in on day one. The onramp asks for effort before it has delivered any value.

This feature turns the empty boxes into a **review step**. The PM gives PMQs a URL — the product's or its company's home page — and PMQs does a quick research pass:

1. reads the home page,
2. uses what it learns to query the search API for more,
3. synthesises the two into a first draft of the product's fields,

and then **pre-populates the Add Product form** with that draft. The PM reviews, edits what's wrong, and saves. The onramp goes from "fill in eight blank fields" to "confirm what we found."

The goal is explicitly a *seamless and inviting* onramp. Two consequences follow from that framing and should be treated as hard constraints:

- **Research never blocks Add Product.** Every stage degrades to "leave the field blank" on failure. A PM who pastes a URL and gets nothing back is no worse off than today; they just fill the form by hand.
- **The PM always reviews before commit.** We pre-fill, we do not auto-create. The research output is a suggestion, not a source of truth, and the UI must read that way.

**What this feature is *not*:** it does not discover or set the GitHub repo (see §12 for the optional bonus). The `org/repo` is still the PM's to provide — PMQs' whole substrate is repo-keyed. The website drives the **news/watchlist/profile** half of a product: the signal side, not the code side.

---

## 2. The user flow

```
Add Product form
  ├─ Repository:  org/repo            (unchanged, still required)
  ├─ Website:     https://…           (NEW — the research input)
  │     └─ [Research this site]       (button; only spends when clicked)
  │
  │   … click …
  │   POST /products/research { url } ──► research pipeline (§5)
  │   ◄── JSON: { name, profile, watchlist{…}, queries[], repo_guess? }
  │
  ├─ (fields fill in, client-side, in place — the "inviting" moment)
  ├─ Nickname / Watchlist / Profile / Lens weights  ← pre-populated, editable
  │
  │   … PM reviews, edits, submits …
  └─ POST /products  ──►  create + persist watchlist/profile (§7)  ──►  seed pass
```

Chosen shape: **prefill-then-review**, done client-side against the create form. The PM sees the fields populate *before* anything is created, can edit or discard freely, and no half-built product row exists if the research is poor. This is cheaper than the alternative (research runs only when the PM asks, not on every create) and it matches "inviting" better than a spinner on submit.

Rejected alternative — **research-on-create** (submit the URL, server creates the product, runs research synchronously, redirects to a filled Settings page): simpler server-side, but it commits a product before review, does network+LLM work inside the create request (slow redirect, and a research failure now sits on the critical path of *creating* the product), and it re-researches on every accidental double-submit. If the client-side approach proves fiddly against the template, this is the fallback — but start with prefill-then-review.

---

## 3. What gets pre-populated

The research output maps 1:1 onto fields that already exist on the create form and in `news_config`. No new product concepts are introduced.

| Field (form `name`) | Source | Notes |
|---|---|---|
| `nickname` | product's common name from the site | drives the slug; "what you call it" — the natural home for the researched name. `display_name` stays `= repo` as today. |
| `product_profile` | LLM synthesis | 2–4 sentences: what it is, who it's for, who competes. This is what the relevance pass judges against — the highest-value field to get right. |
| `wl_industry` | LLM synthesis | e.g. "agent orchestration" |
| `wl_keywords` | LLM synthesis | category/problem terms |
| `wl_companies` | search API + LLM | competitors and adjacent players surfaced by the search pass |
| `wl_products` | search API + LLM | competing/adjacent product names |
| `wl_sources` | search API + LLM | domains that cover this space (folded into every query as a `site:` group — see `news/watchlist.py`) |
| `news_queries` | — | left blank; the raw escape hatch stays the PM's. |
| `repo_guess` (optional) | GitHub link on the page / search | §12 — a *suggestion* into the Repository field, clearly labelled a guess, never auto-accepted. |

Every list field is parsed the same way the rest of the app parses watchlists: one term per line, via `news.watchlist.parse_field`. The research module should emit newline-joined strings (or lists the endpoint joins) so the form textareas populate exactly as a hand-typed watchlist would.

---

## 4. Where it plugs in (grounded in the current code)

Read these before touching anything — the feature is mostly wiring between parts that already exist.

- **`pmqs/api/products.py::add_product`** (`POST /products`) — the create endpoint. Today it reads only `repo` and `nickname` (both `Form`), calls `products.get_or_create_product`, `members.ensure_membership`, then `pipeline.seed_workspace`, and redirects to `/w/{slug}/settings?added=1`. **It ignores every watchlist/profile field the create form renders.** §7 closes that.
- **`pmqs/web/render.py::_product_settings_sections(db, product, prefix, mode, flash)`** — renders the create form when `mode="create"`. In create mode the identity block renders `repo` + `nickname` only; the watchlist block renders `wl_*`, `news_queries`, `product_profile`; lens weights render from defaults. This is where the **Website field + Research button** go, and where the prefill JS is injected.
- **`pmqs/web/render.py::render_product_settings` / `_render_settings_view`** — splice the sections into the app template via `_SETTINGS_SECTIONS_RE` and inject settings JS via `_inject_before_body_close`. The research JS rides in the same injection path. Respect `web/TEMPLATE-CONTRACT.md`.
- **`pmqs/api/settings.py::save_product_settings`** (`POST /w/{slug}/settings`) — the *edit* save. It already parses `wl_industry/keywords/companies/products/sources`, `news_queries`, `product_profile`, and `lens_*`, then calls `products.set_news_config` and `products.set_lens_weights`. **Reuse this parsing verbatim in `add_product`** rather than inventing a second parser.
- **`pmqs/products.py`** — `get_or_create_product`, `set_news_config`, `set_lens_weights`, `get_news_config`. `news_config` is a JSON column on `Product` (`watchlist`/`queries`/`product_profile`); `website` can live here with no migration (§6).
- **`pmqs/news/watchlist.py`** — `parse_field`, `build_queries`, `TERM_FIELDS`, `MAX_QUERIES=24`, `MAX_SOURCES=8`. The research output must be shaped like a watchlist so it flows through `build_queries` unchanged.
- **`pmqs/news/fetch.py`** — the model to copy for the network layer: a **pure parser** (`parse_brave_results`) that is unit-tested offline against a fixture, plus a **thin network wrapper** (`_fetch_query`) that imports `httpx` inline and treats every failure as non-fatal. Mirror this split exactly.
- **`pmqs/settings.py::resolve_brave_key(db)`** — same key the news fetcher uses (raw → env → `~/.hermes`). Never logged, never rendered. **`settings.get_llm(db)`** — the LLM config to pass as `settings_cfg`.
- **`pmqs/llm.py::complete_json(system, user, *, settings_cfg=…, max_tokens=…)`** — the synthesis call. Raises `LlmUnavailable`; callers must catch and degrade.

---

## 5. The research pipeline

New module: **`pmqs/research.py`** (pure logic + prompt) with the network/LLM calls kept thin and individually catchable, mirroring `news/fetch.py`. Three stages, each degrading independently.

### Stage 1 — read the home page (deterministic, no LLM)

- Fetch the URL with `httpx` (imported inline, as `news/fetch.py` does), `timeout≈15s`, following redirects, **capping the response body** (e.g. 250 KB — stop reading past that; a home page over a quarter-megabyte of HTML is a landing page we don't need in full).
- Extract with the **standard-library `html.parser.HTMLParser`** — no new dependency. Pull: `<title>`, `<meta name="description">` / `og:title` / `og:description` / `og:site_name`, the first N headings, and a bounded slab of visible text (strip `<script>`/`<style>`). Also collect outbound `github.com/<org>/<repo>` links (feeds the optional repo guess, §12).
- Truncate the visible text to ~6–8 K characters before it ever reaches the LLM. This is the single biggest token lever — enforce it here, not in the prompt.
- Output: a small dict `{ title, description, site_name, text, github_links[] }`. This alone is enough to seed Stage 2, and enough to pre-fill *something* (name + a rough profile) even if Stages 2–3 fail.

**Degradation:** fetch/parse failure → return an empty dict; the endpoint proceeds with whatever it has (possibly nothing) and the PM fills the form by hand.

### Stage 2 — query the search API (Brave *web* search)

This is the "collect enough from the site to query the search API" step the feature is named for. Stage 1 gives us the product/company name and a rough category; Stage 2 turns those into a handful of searches that surface competitors, category language, and the outlets that cover the space.

- Endpoint: **`https://api.search.brave.com/res/v1/web/search`** (note: *web*, not the `/news/search` the existing fetcher uses — same host, same `X-Subscription-Token` header, same key from `resolve_brave_key`).
- Compose a **small, fixed** set of queries from Stage 1's name/category — default **≤3**, e.g. `"<name>"`, `"<name>" competitors`, `"<name>" alternative` (or `<category> tools`). `count≈5` each. Bound this hard; this runs once at onboarding and must never turn into a per-term fan-out like the recurring news watchlist can.
- Parse results with a **pure `parse_web_results(data)`** function (fixture-tested offline, exactly like `parse_brave_results`): keep title, description, and hostname per result.
- Output: a compact list of `{title, description, host}` snippets handed to Stage 3, plus the set of hostnames (candidate `wl_sources`).

**Degradation:** no key, or every query fails → skip Stage 2 entirely. Stage 3 runs on the home-page text alone (thinner `companies`/`sources`, but a valid profile and industry/keywords).

### Stage 3 — synthesise (one LLM pass)

- One `llm.complete_json` call, `settings_cfg=settings.get_llm(db)`, low temperature, **`max_tokens` capped** (≈1200; tunable via an env var in the spirit of `PMQS_POSITION_DOC_MAX_TOKENS`).
- System prompt: "You are drafting a PMQs product profile and news watchlist from a home page and a few search results. Return **only** JSON with keys `name`, `profile`, `industry[]`, `keywords[]`, `companies[]`, `products[]`, `sources[]`. Be conservative — omit rather than guess; empty arrays are fine." Feed Stage 1's text/description and Stage 2's snippets as the user message.
- Validate the shape defensively (it's a watchlist, not free rein): coerce to lists, drop non-strings, dedup case-insensitively via `parse_field`, and **cap each list** (e.g. ≤8 terms — a watchlist of 40 companies is noise and a bigger news bill later). `sources` should be bare domains.

**Degradation:** `LlmUnavailable` or unparseable JSON → fall back to the deterministic minimum from Stage 1 (`name` = title/`og:site_name`, `profile` = meta description, everything else empty). Still a useful pre-fill; still not a blocked onramp.

### The endpoint

`POST /products/research`, JSON body `{ "url": "…" }`, returns JSON matching the field map in §3 (newline-joined strings for the textareas, or lists the client joins). It **creates nothing** — pure read + suggest. It resolves `db` for the key and LLM config only. Add `test_product_research.py` covering: pure parsers against fixtures, each degradation path (no key / LLM off / fetch fail) returns a well-formed partial, and the endpoint shape.

---

## 6. Storage

Persist the entered `website` so the product can be re-researched later and so Settings can show it. **Store it inside `news_config`** as `news_config["website"]` — it is JSON already, so this needs **no migration** (consistent with `watchlist`/`queries`/`product_profile` living there). Extend `products.get_news_config`'s `_NEWS_FIELDS` to include `website`, thread it through `set_news_config`, and surface it as a field on the Product Settings (edit) view too, with a "Re-research" affordance reusing the same endpoint.

Do **not** add a `website` column. (The dead `accent` column is a standing reminder that unused columns accrete here — don't add another.)

---

## 7. The gap that must close first

`add_product` (`POST /products`) does not persist the watchlist/profile fields the create form renders. **Until this is fixed, pre-population is cosmetic** — the PM would review lovely researched fields, hit "Add product," and watch them vanish, landing on an empty Settings page.

Fix, in `add_product`:

1. Accept the same `Form` params `save_product_settings` accepts (`wl_*`, `news_queries`, `product_profile`, and the `lens_*` read off the raw form). Factor the parsing into one shared helper so the two endpoints can't drift.
2. **Detect create-vs-resolve.** `get_or_create_product` may resolve to an *existing* product (a colleague already added this repo — the shared-Product case). In that case **do not** overwrite their `news_config` with this PM's prefill. Only apply the researched fields when the row was newly created. `get_or_create_product` currently returns the product without signalling newness — have it return a `(product, created)` pair (or check existence before calling), and gate the `set_news_config`/`set_lens_weights` on `created`.
3. Apply `set_news_config` / `set_lens_weights` **before** `seed_workspace`, so the initial lens/seed pass runs against the researched watchlist and profile instead of against nothing. This is a real quality win, not just ordering hygiene — the first inbox batch lands already scoped to the product.

Acceptance: a create POST carrying watchlist/profile persists it on a *new* product; the same POST against an *existing* repo leaves that product's config untouched; the seed pass sees the config.

---

## 8. Work breakdown (issues → PRs)

File issues **inert/unlabelled** for Matt's triage (status labels auto-dispatch the agents). Each PR: **`base=main`, non-empty `closingIssuesReferences`, one issue per PR** — the intake-wild invariant (§10). Suggested split:

- **Issue A — persist watchlist on create (§7).** Server-only, no research. Landable on its own and worth landing first: it fixes a live bug (create form shows fields it discards) independent of the research feature. PR closes A.
- **Issue B — research module + endpoint (§5).** `pmqs/research.py` (pure parsers + synthesis), `POST /products/research`, `test_product_research.py`. No UI. Fully testable offline via fixtures + degradation paths. PR closes B.
- **Issue C — website field, Research button, prefill JS (§2, §4).** The create-form UI: Website input + button, client-side call to `/products/research`, populate fields by `name`. Depends on B (endpoint exists) and benefits from A (fields now persist). Respect the template contract. PR closes C.
- **Issue D — persist `website` + re-research on edit (§6).** `news_config["website"]`, shown on Product Settings with a re-research affordance. Small; can fold into C if Matt prefers fewer PRs. PR closes D.

Land order: **A → B → C (→ D)**. A and B are independent and can be parallel; C needs both.

---

## 9. Behaviour & cost bounds

| Situation | Behaviour |
|---|---|
| PM never clicks Research | Zero network, zero LLM. Add Product behaves exactly as today. |
| Research clicked, all stages succeed | Fields fill in place; PM reviews and edits; submit persists. |
| No Brave key | Stage 2 skipped; profile/industry/keywords still drafted from the page; companies/sources thin or empty. No error shown beyond a quiet "couldn't reach search." |
| LLM off/unavailable | Deterministic fallback: name + meta-description profile; watchlist blank. |
| Home page unreachable | Nothing pre-fills; a quiet inline note; form is fully usable by hand. |
| Repo already exists (colleague added it) | Product resolves to the shared row; **prefill is not applied** to their config (§7.2). |
| Double-click Research | Debounce client-side; the endpoint is idempotent (creates nothing) so a duplicate call is just wasted spend — the debounce is the guard. |

**Cost discipline** (a standing directive on this codebase — do things properly but cheaply, and don't spend tokens where they aren't needed): research runs **only on explicit click**, not on paste or on every create. One bounded page fetch, ≤3 search calls, **one** LLM pass with a capped `max_tokens`. Auto-running research on URL-paste is deliberately *not* in this plan — it spends on every keystroke-completed URL; if wanted, it's a later opt-in, not the default (§12).

---

## 10. Repo traps (read before opening a PR)

- **The intake-wild invariant.** Every PR to this repo needs `closingIssuesReferences` non-empty, which means **`base=main` AND a real issue to close**. A stacked PR (`base != main`) registers *zero* linked issues because GitHub only links "Closes #N" against the default branch; a PR with no issue behind it links nothing either. Agent Intake then classifies it `source:wild` and loops, spawning stub issues (this has happened twice, ~11 + 1 stubs). This applies to **this docs PR too** — open it against an inert tracking issue. Verify with the GraphQL `closingIssuesReferences` field, and re-query a few seconds after opening (indexing lags).
- **httpx is a *test-only* extra**, not a runtime dependency (`pyproject.toml`: it's under `[project.optional-dependencies].test`). `news/fetch.py` gets away with `import httpx` inline because it degrades on `ImportError`. **Do the same** — import inline inside the network wrappers and treat `ImportError` as just another "search unavailable" — or promote httpx to a runtime dep in the same PR. Don't add a top-level `import httpx` to a module that loads at import time.
- **No CI runs pytest (#79).** Every "suite green" claim is a *local* `pytest` run plus manual page loads. There is no safety net — run the suite yourself and load the create form in a browser before calling it done.
- **The app template is production code spliced by regex.** `render.py` injects into `app.html` via anchored patterns; `web/TEMPLATE-CONTRACT.md` documents them and **no test asserts on the markup**, so it can break with the suite green. The create-form edits and the prefill JS live inside the settings-sections region and the before-`</body>` injection — keep within the contract, and load the page to confirm.
- **Keys never touch logs or the response.** `resolve_brave_key` and the LLM key stay server-side; the `/products/research` response carries only field suggestions. Don't echo the URL's fetched HTML back to the client either — return the distilled fields only.
- **`get_or_create_product` can return an existing row.** The shared-Product case is real and is exactly when *not* to apply prefill. See §7.2 — this is the easiest thing in the whole plan to get wrong.

---

## 11. Out of scope

- Auto-creating the product without review. We pre-fill; the PM commits.
- Recurring/scheduled re-research. Research is an onboarding action (plus a manual re-research button); it is not a background job.
- Deep multi-page crawling. One page (home), optionally a couple of search snippets. Not a site spider.
- Setting lens weights from research. Defaults stay; the PM tunes. (Profile + watchlist are plenty for MVP.)
- Any new dependency beyond what's already present (stdlib HTML parsing; httpx handled as above).

---

## 12. Needs a human (Matt)

1. **Repo discovery from the site** — Stage 1 already collects `github.com/<org>/<repo>` links from the page. Do you want the research pass to *suggest* one into the Repository field (labelled a guess, never auto-accepted), or leave repo entirely manual? Low effort, but it's a product call about how much to infer.
2. **Auto-run on paste vs. explicit button.** The plan defaults to an explicit "Research this site" button (spends only on click). Auto-running when a valid URL is pasted is more magical but spends on every completed URL. Your call — the button is the safe default.
3. **`display_name` on create.** Today create has no `display_name` field and sets `display_name = repo`; the researched name lands in `nickname`. If you'd rather the researched name become the `display_name`, add that field to the create identity block. Minor.
4. **Search provider.** The plan reuses Brave (same key as news) via its *web* search endpoint. If onboarding research should use a different/better search source than the news watchlist, that's a decision to make before Issue B.
5. **Prefill vs. research-on-create.** The plan recommends client-side prefill-then-review. If you'd prefer the simpler server-side "submit URL → create → land on filled Settings," §2 describes that fallback and its tradeoffs.
