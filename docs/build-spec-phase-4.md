# PMQs — Build Spec: Phase 4 (News Ingestion + Interpretive News Lens)

> **For Hermes:** Use the `subagent-driven-development` skill to implement this plan
> task-by-task, with two-stage review per task.
> **Do not implement until the product owner has answered the OPEN QUESTIONS below.**

**Goal:** Add the second input source — industry/competitive news — so PMQs can generate
the *provocative, externally-informed* questions that make a PM stop and take something
to the war room. Configure news sources in Settings, ingest raw items into a separate
staging store, run an **interpretive (LLM) news-relevance pass** that turns relevant
items into scored Inbox Questions with attributed-but-hedged citations, and let those
flow through the existing war-room → outcomes loop.

**Why this is the interesting phase (product owner framing, 2026-07-13):** the loop
"configure news sources → a challenging question appears in the Inbox → PM opens the
war room → discussion → typed outcome" is where the product's thesis gets tested. Phase 4
builds exactly that loop for the news source.

**Architecture:** Same shape as Phases 0–3. News is the **interpretive** trigger type
(product-design.md): unlike structural repo triggers (deterministic, no LLM), news
relevance IS an LLM judgment. Raw news items live in a NEW staging store, deliberately
OUTSIDE the Issues substrate and separate from `questions` (raw ≠ evidence). An
interpretive pass promotes relevant raw items into `questions` (source='news'),
reusing the existing framing/dedup/scoring/context-feed machinery. News evidence uses
**attributed-but-hedged citation** (source + title + url + "reportedly/according to"),
distinct from repo evidence's direct receipts.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (SQLite), LiteLLM via `pmqs/llm.py`,
server-rendered HTML. News fetching: stdlib/`httpx` for RSS/Atom + JSON feeds first
(cheap, no keys); paid aggregator APIs are a later fallback (hosted-first, per design).

**Prerequisites (done, remote `main` @ 7abdabb):**
- Inbox render + pipeline; triggers; framing/dedup/scoring; war-room; 8-lens; outcomes;
  unified context-feed; Settings store (+ /settings page).
- `questions` table has `source` (currently 'system'|'pm'); we add 'news'.

**Hard rules (unchanged):**
- Never `agentos apply`/`upgrade` against `agentos-pmqs` (guard test stays green).
- Policies never to GitHub.
- **NEW invariant:** raw news items must NEVER be written into the Issues substrate or
  pushed to GitHub. They live only in the hosted staging store until explicitly promoted
  to a Question (and even then, only as a citation, never as a GitHub Issue body dump).

---

## Also fix in this phase (small, related): Settings is unreachable from the UI

The `/settings` page exists but there is **no nav link** — the mockup's left rail only
has Inbox/Workspace/Outcomes. Since news sources are configured in Settings, Phase 4
must add a Settings entry point (a rail link or a gear icon) via the injected live-JS,
so the news-source config is actually reachable. Small task, folded into Task 5.

---

## Scope boundaries

**In scope (Phase 4):**
1. News-source configuration in Settings (list of feed URLs; enable/disable).
2. Raw news staging store (separate table, outside Issues/questions).
3. Ingestion: fetch configured feeds → parse → write raw items (dedup by URL).
4. Interpretive news-relevance pass (LLM): judge which raw items matter for THIS
   product, promote relevant ones to `questions` (source='news') with hedged citations.
5. Reuse framing/dedup/scoring so news Questions rank in the same Inbox alongside
   repo-trigger and PM questions; feed the unified context-feed into the relevance pass.
6. Inbox distinguishes news-sourced questions (a lens/source pill) and the war-room
   Evidence tab renders news citations (attributed-but-hedged) correctly.
7. Settings reachable from the UI.

**Out of scope (later phases — do NOT build):**
- Full paid news-aggregator integrations (keep a clean fetch interface; RSS/JSON first).
- The "homepage/competitor-site watcher" connector (that's a distinct source; not news).
- Scheduled/automatic ingestion daemon — Phase 4 ingests on an explicit action/endpoint
  (a cron job can call it later; do not build the scheduler here). See Q5.
- Auth/multi-tenant, OSS packaging.
- Analytics sources (PostHog/Stripe) — later phases per the 3Qs connector roadmap.

---

## OPEN QUESTIONS — RESOLVED by product owner (2026-07-15)

**Q1 — News source: BRAVE SEARCH API only.** The Brave API key is configured by the
user in Settings (stored as an env-var reference or runtime field, NEVER hardcoded /
committed — same security pattern as the Anthropic key). Fetcher interface still
abstract so other sources drop in later.

**Q2 — Relevance pass: (a) ONE BATCHED LLM call** per ingestion for now; per-item is a
future refinement.

**Q3 — Inbox cap: TOP 3 news questions per run, AND a relevance-score threshold below
which nothing is promoted.** If nothing clears the bar, show an explicit "nothing
relevant today" message rather than promoting weak items. Cap + threshold configurable.

**Q4 — Relevance judged against a free-text "product profile" field in Settings.**

**Q5 — Ingestion: MANUAL endpoint/button only** for now (`POST /news/ingest` + a
Settings "Fetch news now" button). Cron later — likely surfaced/configured in Settings.

**Q6 — Raw item retention: KEEP, no auto-purge in Phase 4.** Mark processed.

**Q7 — Evidence: `{source} — "{title}" ({date}), via {url}` + hedged framing.** Confirmed.

### SECURITY NOTE
The Brave key was shared in plaintext chat and must be treated as compromised — rotate
it. It is NOT stored in the repo. Runtime only: Settings field or `BRAVE_API_KEY` env
var, kept out of all rendered HTML (masked), never committed.

---

## Tasks (TDD; each ends with a commit) — DRAFT, pending answers

> Shapes assume the "my lean" answers; finalized after Q1–Q7.

### Task 1: News-source config in Settings (Brave key + product profile + caps)

**Objective:** Persist Brave Search config (API key ref + query terms), a product-profile
string, and the news caps (top-N + relevance threshold) in the Settings store.

**Files:** `pmqs/pmqs/settings.py` (news accessors), `tests/test_settings_news.py`.
**Design:** `get_news_config(db)` → {api_key_ref, api_key_raw (masked, never rendered),
queries: [str], product_profile: str, top_n: int=3, min_relevance: float}. Setters
mirror the LLM section. Brave key handled exactly like the Anthropic key: env-var ref
preferred, raw entry masked and never echoed into HTML.
**Commit:** `feat(phase4): news/Brave settings (key ref, queries, profile, caps)`

### Task 3: Brave Search fetcher/ingestion

**Objective:** Query the Brave Search API for the configured terms, parse results, write
new raw items (dedup by URL).

**Files:** `pmqs/pmqs/news/fetch.py` (Brave client via httpx; `X-Subscription-Token`
header from the resolved key), `pmqs/pmqs/news/__init__.py`, `tests/test_news_fetch.py`
(parse a saved Brave JSON fixture offline; NO network + NO key in tests).
**Design:** `ingest(db, config) -> list[NewsItem]`. Endpoint:
`GET https://api.search.brave.com/res/v1/news/search?q=...` (news endpoint; fall back to
web search if needed). Key resolved from Settings (raw) or `BRAVE_API_KEY` env — never
hardcoded. Network/HTTP failure is non-fatal (skip + log). Pure result-parser unit-tested
against a fixture. Dedup by URL against existing NewsItems.
**Commit:** `feat(phase4): Brave Search news fetcher + ingestion`

### Task 2: Raw news staging store

**Objective:** A table for raw news items, OUTSIDE Issues/questions (raw ≠ evidence).

**Files:** `models.py` (`NewsItem`: id, source_label, title, url UNIQUE, summary,
published_at, fetched_at, processed BOOL), `repository.py` (create/list/mark-processed,
dedup-by-url), `tests/test_news_store.py`.
**Commit:** `feat(phase4): raw news staging store`

### Task 3: Feed fetcher/ingestion

**Objective:** Fetch configured feeds, parse entries, write new raw items (dedup by URL).

**Files:** `pmqs/pmqs/news/fetch.py` (RSS/Atom/JSON parsing; stdlib/httpx), 
`pmqs/pmqs/news/__init__.py`, `tests/test_news_fetch.py` (parse fixtures offline; no
network in tests).
**Design:** `ingest(db, sources) -> list[NewsItem]`. Network failure per-source is
non-fatal (skip + log). Pure parser tested against a saved RSS/JSON fixture. (Depends Q1.)
**Commit:** `feat(phase4): news feed fetcher + ingestion`

### Task 4: Interpretive news-relevance pass

**Objective:** THE interpretive pass. One batched LLM call judges which unprocessed raw
items are relevant to the product profile, and frames the relevant ones into Questions.

**Files:** `pmqs/pmqs/news/relevance.py`, `tests/test_news_relevance.py`.
**Design (assuming Q2=batch, Q3=top-3, Q4=profile):**
`promote_relevant(db) -> list[Question]` →
  - gather unprocessed raw items + product profile + context-feed block
  - ONE LLM call returns the relevant subset (top N) with hedged title/description +
    citation per item
  - create `questions` rows `source='news'`, evidence = news citation (type='news',
    url, source, hedged), status='proposed'
  - dedup against each other AND (lightly) existing proposed questions; score via
    existing `scoring.score_question`; mark raw items processed
  - degrade: LLM unavailable → promote nothing, mark nothing, no crash
**Commit:** `feat(phase4): interpretive news-relevance pass → Inbox questions`

### Task 5: UI — Inbox news pills, Evidence citations, Settings reachable, ingest button

**Objective:** Make it visible and operable end-to-end.

**Files:** `web/render.py` (news source pill on cards; render news citations in the
Evidence tab; add a Settings nav link via injected JS), `api/news.py`
(`POST /news/ingest` → fetch + promote; redirect), `api/settings.py` (news-source +
product-profile fields + "Fetch news now"), `api/app.py` (router),
`tests/test_render_news.py`, `tests/test_api_news.py`.
**Design:** source='news' cards get a distinct pill; Evidence tab handles
`type='news'` items with attributed-but-hedged formatting (Q7). Settings link fixes the
"no way to reach /settings" gap. (Depends Q5, Q7.)
**Commit:** `feat(phase4): news UI (pills, citations, Settings link, ingest button)`

### Task 6: End-to-end verification (real feed, real LLM)

**Objective:** Prove the money loop: configure a real RSS feed → ingest → a provocative
news Question appears ranked in the Inbox → open it in the war room → real probe
discussion → produce a typed outcome. Full `pytest -q` green. Clean up.
**Commit:** `test(phase4): end-to-end news → question → war-room → outcome`

---

## Files likely to change (summary)

- Create: `news/__init__.py`, `news/fetch.py`, `news/relevance.py`, `api/news.py`,
  and 5 test files.
- Modify: `models.py` (NewsItem), `repository.py` (news queries + source='news'
  questions), `settings.py` (news sources + product profile + top-N cap),
  `api/settings.py` (news config UI + fetch button), `web/render.py` (news pills +
  citations + Settings nav link), `api/app.py` (news router), `config.py` if needed.

## Risks / tradeoffs

- **Cost.** The relevance pass is the new recurring LLM spend. Mitigations: batch call
  (Q2), top-N cap (Q3), manual ingest only (Q5) so it never runs unprompted.
- **Feed reliability / parsing.** Feeds vary (RSS vs Atom vs JSON, malformed entries).
  Mitigation: per-source try/except, tested pure parser, dedup by URL.
- **Inbox flooding.** News could swamp the "short ranked list." Mitigation: top-N cap +
  the same unified scoring so news competes fairly, not floods.
- **Raw-vs-evidence discipline.** Keep raw items in their own store; only promoted
  Questions carry citations. Never let raw news touch Issues/GitHub (new invariant test).
- **Hedged attribution.** News claims are second-hand; the framing prompt must hedge
  ("reportedly", "according to {source}") and always cite — enforced in the prompt +
  a test that promoted news Questions carry a citation.

## Verification checklist

- [ ] All new tests pass with `PMQS_LLM_MODE=off` (parser + store tested offline).
- [ ] Real e2e: a configured RSS feed yields a ranked news Question that opens into a
      war-room and produces an outcome.
- [ ] `test_no_hazard.py` passes; a test asserts no raw news item or news Question path
      writes to GitHub except a deliberate Issue outcome.
- [ ] Inbox/Workspace/Outcomes/Settings unregressed; Settings now reachable from the UI.
- [ ] News Questions ranked by the SAME scoring formula; carry attributed-but-hedged
      citations.
