# PMQs — Build Spec: Polish Phase (bug fixes + UX hardening, pre–Phase 5)

> **For Hermes:** small, safe, test-backed fixes to what already works. No new phase
> features, no tenancy, no auth. Each fix is independently committed and verified.
> Deliberately chosen to be low-risk and NOT to conflict with the eventual Phase 5
> refactor.

**Goal:** Fix the concrete bugs and rough edges visible in the running app (Phases 0–4)
so the demo is solid, before taking on the expensive/high-risk Phase 5. Every item below
was found by reading the current code, not guessed.

**Prerequisites:** remote `main` @ 68d1ee5, 95 tests green.

**Ground rules:** each fix gets a failing test first (or a test that locks the corrected
behavior), then the fix, then green. Keep the LLM off in tests. Commit per fix.

---

## Confirmed bugs (found in code)

### B0a — Home page shows a DIFFERENT list after visiting a War Room (the routing bug)
**Symptom (reported):** going back to home after a war-room session shows a different set
of questions (looks like GitHub issues) and a header that isn't on the root view.
**Root cause (confirmed):** `GET /` (`api/inbox.index`) has TWO data paths: if the DB has
persisted questions it shows those; if the DB is empty it falls back to `_live_shims()`
which renders raw GitHub issues live. Opening a war-room calls `open_workspace`, which
**persists a question row** (resolving the `issue:<n>` pseudo-id). So after any war-room
visit the DB is no longer empty and `/` flips from the live-GitHub view to the
persisted-questions view — a different list. The stray "header" is the shared mockup not
resetting to the Inbox view (a non-inbox view left active in the rendered HTML).
**Fix:**
  - Make `/` deterministic: decide ONE canonical Inbox source. Recommended: the
    persisted questions are the Inbox; the live-GitHub read-through should NOT silently
    replace it. Instead, when the store is empty show an explicit empty-state with a
    "Pull from repo" (run `/refresh`) action, rather than auto-swapping to a different
    data set. (Removes the Jekyll/Hyde behavior.)
  - Ensure the rendered `/` always lands on the Inbox view (force `showView('inbox')` /
    the inbox view is `active`), so no war-room/workspace header bleeds in.
- Files: `pmqs/pmqs/api/inbox.py`, `pmqs/pmqs/web/render.py`, `tests/test_inbox_route.py`.
- Test: after persisting a question (simulating a war-room open), `GET /` still renders
  the Inbox view (not workspace), and does not switch data sources mid-flight; empty
  store shows the empty-state, not a silent GitHub dump.

### B0b — Position Document appears not to persist (new session each open)
**Symptom (reported):** a previously-generated Position Doc isn't shown later.
**Root cause (confirmed):** the generate-once/persist logic is correct
(`set_position_doc` writes it; `workspace_view` reads `sess.position_doc`). BUT
`POST /workspace/open` creates a **brand-new session every time**. The doc was saved on
the earlier session; reopening the same question yields a new session with no doc — so it
looks unpersisted.
**Fix:** make "open war-room for question X" **reuse the existing open session** for that
question instead of always creating a new one. `open_workspace` should look up an open
session with the same `question_id` (most recent) and redirect to it; only create a new
session when none exists (or when the PM explicitly starts a fresh one / branches).
- Files: `pmqs/pmqs/api/workspace.py`, `pmqs/pmqs/repository.py`
  (`find_open_session_for_question`), `tests/test_workspace_session_reuse.py`.
- Test: opening the same question twice returns the SAME session id; a Position Doc
  generated in the first visit is present on the second; branching still makes a child.

### B1 — Inbox never shrinks: dismissed/promoted questions still show
`repository.list_questions` returns ALL questions regardless of status, and the Inbox
renders them all. Dismissing or pushing a question to an Issue leaves it in the ranked
list forever. **Fix:** `list_questions` should, by default, exclude `dismissed` and
`promoted` (keep `proposed` + `saved`). Add a `statuses`/`include_all` param so the
`/api/questions` debug view and any admin need can still see everything.
- Files: `pmqs/pmqs/repository.py`, `pmqs/pmqs/api/inbox.py` (pass the filter),
  `tests/test_repository_inbox.py` (new).
- Test: create proposed/saved/dismissed/promoted; default Inbox list returns only
  proposed+saved, ranked; `include_all=True` returns all.

### B2 — Save/Dismiss buttons navigate to a JSON blob
`pmqsSetStatus` does a form POST to `/questions/{id}/status`, but that route returns
`JSONResponse`, so the browser lands on raw JSON instead of the refreshed Inbox.
**Fix:** make the status route redirect (303 → `/`) for the form path, OR have the JS use
fetch + reload. Simplest + consistent with the rest of the app: **303 redirect to `/`**.
Keep a JSON API variant if `/api/...` needs it, but the button path must redirect.
- Files: `pmqs/pmqs/api/inbox.py`, `tests/test_api_inbox_status.py` (new).
- Test: POST status returns 303 → `/`; the question's status changed; a dismissed
  question no longer appears in the next `GET /`.

### B3 — Save/Dismiss on live read-through cards silently no-op
On a fresh Inbox (no pipeline run), cards carry pseudo-ids `issue:<n>` (not real rows).
`pmqsSetStatus('issue:5','dismissed')` hits `/questions/issue:5/status` →
`update_question_status` finds nothing → 404/no-op, confusing the user.
**Fix:** either (a) hide Save/Dismiss on pseudo-id cards, or (b) resolve `issue:<n>` by
persisting on demand (like `/workspace/open` already does) before setting status.
Recommend **(b)** for consistency — extract the pseudo-id→Question resolution already in
`api/workspace.py` into a shared helper and reuse it here.
- Files: `pmqs/pmqs/api/inbox.py`, `pmqs/pmqs/api/workspace.py` (extract helper),
  `pmqs/pmqs/repository.py` if needed, `tests/test_pseudo_id_resolve.py` (new).
- Test: setting status on an `issue:<n>` card persists the issue then applies the status;
  the card resolves to a real row.

### B4 — Inbox doesn't show the news ingest flash
`POST /news/ingest` redirects to `/?news=<n|none>` (Phase 4), but `GET /` ignores the
`news` query param, so the PM gets no feedback ("3 new questions from news" / "nothing
relevant today"). **Fix:** read `?news=` in `index()` and render a small, quiet banner
(reuse mockup styling) above the Inbox list.
- Files: `pmqs/pmqs/api/inbox.py`, `pmqs/pmqs/web/render.py` (optional `flash` arg),
  `tests/test_render_flash.py` (new).
- Test: `render_inbox(..., flash="3")` shows the count banner; `flash="none"` shows the
  "nothing relevant today" message; no flash → no banner.

### B5 — All news questions default to the `competitive_positioning` lens
`news/relevance.py` hardcodes `lens_tags=["competitive_positioning"]` for every promoted
item. The relevance LLM could pick the most fitting lens per item (from the 8-lens
taxonomy). **Fix:** ask the relevance prompt to return a `lens` per item, validate it
against `config.LENS_WEIGHTS` keys, fall back to `competitive_positioning` if missing/
invalid. Cheap (same call), better ranking + filtering.
- Files: `pmqs/pmqs/news/relevance.py`, `tests/test_news_relevance.py` (extend).
- Test: a stubbed LLM returning `lens="unit_economics"` yields that lens tag; an invalid/
  missing lens falls back to the default.

### B6 — `_proposed_for` shows ALL proposed system questions, not this session's
In `api/workspace.py`, `_proposed_for` returns every proposed system question globally,
so the Workspace "Proposed questions" tab shows unrelated Inbox items, not the ones the
8-lens run produced for THIS session. **Fix:** tag lens-produced questions with their
session (add a nullable `origin_session_id` to Question, set it in
`lenses.run_session_lenses`), and filter `_proposed_for` to that session.
- Files: `pmqs/pmqs/models.py` (add column + backfill-safe default), `repository.py`,
  `pmqs/pmqs/lenses.py`, `pmqs/pmqs/api/workspace.py`, `tests/test_lenses.py` +
  `tests/test_api_workspace.py` (extend).
- Test: lenses run in session A tag their questions to A; session B's Proposed tab does
  not show A's lens output.

## UX/robustness hardening (small)

### H1 — Consistent 404 pages, not raw JSON, for browser routes
Browser-facing routes (`/workspace/{bad}`, etc.) sometimes return a bare string or JSON.
Return a minimal styled HTML 404 for GET browser routes; keep JSON for `/api/*`.
- Files: `pmqs/pmqs/web/render.py` (tiny `render_error`), the GET routes.
- Test: `GET /workspace/nonexistent` → 404 with HTML, not a stack/blob.

### H2 — Filter pills on the Inbox actually filter server-side by lens
The mockup's filter pills (All/Urgent/Asked/System/Saved) run client-side on the mockup
fixtures; with real data they should filter the real list. Minimum: wire the lens/source
filters to `GET /?lens=` (already supported) and the source pills to a `?source=` param.
- Files: `pmqs/pmqs/api/inbox.py` (accept `source`), `repository.list_questions`
  (source filter), `web/render.py` (pills link to the param).
- Test: `?source=news` returns only news questions; `?source=pm` only PM ones.

### H3 — Stale-server foot-gun: document the run/stop recipe in the README
We hit "stale uvicorn on :8000 serves old code" repeatedly. Add a short "Running locally"
README section with the kill/verify/start recipe (also captured in the mockup-to-webapp
skill P3). Docs only.
- Files: `pmqs/README.md`.

## Test/health

### T1 — Full regression + manual click-through
After all fixes: `pytest -q` green; boot the server once (background + readiness watch),
click-through Inbox → dismiss (list shrinks) → quick-add → open war-room → run lenses →
this-session proposed only → news ingest flash. Clean up seed data + DB.

---

## Sequencing & risk

Order: B1 → B2 → B3 → B4 → B5 → B6 → H1 → H2 → H3 → T1. B1/B2 are the most visible
("Inbox never clears", "buttons show JSON"), do them first. B6 adds a Question column —
lowest-churn to do before Phase 5 rather than after. None of these conflict with Phase 5;
they're additive fixes to logic Phase 5 will scope by workspace later.

**Explicitly out of scope:** tenancy, auth, Postgres, new outcome types, the Impacts tab
(needs cost telemetry), no-reload AJAX (form-POST is fine for the prototype).

## Verification checklist
- [ ] `pytest -q` green (new tests for B1–B6, H1–H2).
- [ ] Dismiss/push removes items from the Inbox; buttons refresh (no JSON page).
- [ ] Live read-through cards' buttons work (pseudo-id resolved).
- [ ] News ingest shows a flash; nothing-relevant message appears when appropriate.
- [ ] News questions carry a sensible per-item lens.
- [ ] Workspace Proposed tab shows only this session's lens output.
- [ ] No secrets committed; guard test (no apply/upgrade) green.
