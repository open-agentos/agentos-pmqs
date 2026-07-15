# PMQs — Build Spec: Phase 3 (Remaining Outcome Types + Unified Context-Feed)

> **For Hermes:** Use the `subagent-driven-development` skill to implement this plan
> task-by-task, with two-stage review (spec compliance, then code quality) per task.
> **Do not implement until the product owner has answered the OPEN QUESTIONS below.**

**Goal:** Make the non-Issue outcome types real — Policy, Document, Meeting (and the
already-working Question/Issue) — and build the single **unified context-feed** that
injects those durable outcomes back into agent prompts (war-room, framing, lenses), so
the product "eats its own cooking": decisions the PM records become context that shapes
future agent behavior. This is the "Memory"-like mechanism from `product-design.md`.

**Architecture:** Same shape as Phases 0–2. Outcomes already persist as typed JSON rows
(`outcomes` table, Phase 2). Phase 3 adds: (a) per-type payload shapes + light
validation, (b) a `context_feed` module that assembles active Policies/Documents/
Meeting-agendas into a single context block, (c) injection of that block into the
existing LLM call sites via one shared helper, and (d) the Outcomes ledger view wired
to real data. No new framework; reuse `pmqs/llm.py`, `repository.py`, `render.py`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (SQLite), LiteLLM via `pmqs/llm.py`,
server-rendered HTML reusing the mockup's Outcomes view.

**Prerequisites (done, on remote `main` @ a64311c):**
- `outcomes` table with `type`, `payload` (JSON), `session_id`, `github_ref`.
- `POST /workspace/{id}/outcome` writes policy/document/meeting/question rows (row-only)
  and pushes Issue to real GitHub. Policy can never carry a `github_ref` (enforced).
- War-room, 8-lens, framing, position-doc all call `pmqs/llm.py` with settings-aware
  resolution and graceful fallback.

**Hard rules (unchanged):**
- Never run `agentos apply`/`upgrade` against `agentos-pmqs` (guard test must pass).
- **Policies must NEVER be written to GitHub** — hosted-store only, private to the
  customer. Phase 3 adds MORE code paths touching policies, so re-assert this in tests.

---

## Scope boundaries

**In scope (Phase 3):**
1. Per-type payload shapes + validation for Policy, Document, Meeting (Question/Issue
   already done).
2. The **unified context-feed**: one mechanism that gathers active durable outcomes and
   renders them into a context block for agent prompts. Same plumbing for all non-Issue
   types (no per-type bespoke integration — that's the explicit product requirement).
3. Injecting the context block into war-room, framing, and lens prompts via one helper.
4. Outcomes ledger view (`/outcomes` or the mockup's Outcomes tab) wired to real rows,
   with the summary strip counts by type.
5. Basic lifecycle for durable outcomes: create, list, view, and
   **deactivate/archive** (so a stale Policy stops feeding context) — minimal, no full
   edit UI required.

**Out of scope (later phases — do NOT build):**
- News ingestion / the separate raw-news staging store (Phase 4).
- Google Docs / Google Calendar integrations (explicitly not dependencies; a Meeting may
  hold an agenda + an optional link string, nothing more).
- Auth / multi-tenant (Phase 5).
- Structured Policy rule schema — Policy stays free-form text at MVP ("similar to
  Memory"), per product-design.md. Do NOT design a rule DSL.
- Vector search / embeddings for context selection unless an OPEN QUESTION says so.

---

## OPEN QUESTIONS — RESOLVED by product owner (2026-07-13)

**Q1 — Context-feed selection: (a) ALL ACTIVE, newest-first, char-budget capped.** No
per-session LLM relevance call (keeps cost bounded). Policies always included.

**Q2 — Call sites that consume the feed: WAR-ROOM + 8-LENS ONLY.** Framing and
position-doc do NOT get the context block in Phase 3.

**Q3 — Policy scope: GLOBAL.** All active policies feed every session.

**Q4 — Meeting fields: `title` + `agenda` (free text) + optional `calendar_link`
(string only, no integration).** Confirmed.

**Q5 — Ledger: wire the EXISTING mockup Outcomes view** to real rows + real summary
strip (mirror the Inbox wiring).

**Q6 — Context budget: configurable char cap in Settings, DEFAULT ~4000 chars.**
Policies-first truncation so standing rules are never dropped.

---

## Tasks (TDD; each ends with a commit) — DRAFT, pending answers

> Task shapes below assume the "my lean" answers. They will be finalized once Q1–Q6 are
> confirmed; anything an answer changes is marked.

### Task 1: Per-type outcome payloads + validation

**Objective:** Give Policy/Document/Meeting well-defined payload shapes and validate on
create, without over-engineering (free-form text bodies, per product design).

**Files:**
- Create: `pmqs/pmqs/outcomes/types.py` (payload builders/validators per type)
- Modify: `pmqs/pmqs/api/outcomes.py` (use validators; accept per-type fields)
- Test: `pmqs/tests/test_outcome_types.py`

**Design:** small pure functions `build_policy(text)`, `build_document(title, body)`,
`build_meeting(title, agenda, calendar_link="")` returning the JSON payload. Reassert:
policy build path never sets github_ref. (Depends on Q4 for Meeting fields.)

**Steps:** failing test → implement → pass → commit
`feat(phase3): typed outcome payloads (policy/document/meeting)`

### Task 2: Durable-outcome lifecycle (list/view/deactivate)

**Objective:** Query active durable outcomes and archive stale ones.

**Files:**
- Modify: `pmqs/pmqs/models.py` (add `outcomes.active BOOLEAN default 1`) — or reuse a
  payload flag; prefer a column for queryability.
- Modify: `pmqs/pmqs/repository.py` (`list_durable_outcomes(active_only=True)`,
  `deactivate_outcome(id)`)
- Test: `pmqs/tests/test_outcome_lifecycle.py`

**Steps:** failing test → implement → pass → commit
`feat(phase3): durable outcome lifecycle (active flag + queries)`

### Task 3: Unified context-feed assembler (`context_feed.py`)

**Objective:** THE core Phase 3 piece. One function assembles active durable outcomes
into a single context block (string) for agent prompts. Same plumbing for all types.

**Files:**
- Create: `pmqs/pmqs/context_feed.py`
- Modify: `pmqs/pmqs/config.py` or Settings (char budget, per Q6)
- Test: `pmqs/tests/test_context_feed.py`

**Design (assuming Q1=a, Q3=global, Q6=char cap):**
`build_context_block(db, *, char_budget=None) -> str` →
  - fetch active Policies (always in), then Documents, then Meeting agendas, newest first
  - format each as a labelled section ("STANDING POLICIES", "REFERENCE DOCUMENTS",
    "MEETING AGENDAS")
  - truncate to the char budget, policies-first so they're never dropped
  - return "" when nothing active (callers add nothing to the prompt)

**Steps:** failing tests (policies always included; budget truncation; empty→"") →
implement → pass → commit `feat(phase3): unified context-feed assembler`

### Task 4: Inject context-feed into agent prompts

**Objective:** Wire the context block into the chosen call sites via ONE shared helper,
so it's uniform and easy to extend.

**Files:**
- Modify: `pmqs/pmqs/warroom.py` (prepend context block to the war-room prompt)
- Modify: `pmqs/pmqs/lenses.py` (context block into triage/generation prompts)
- (Q2 may add: `framing.py`, `position_doc.py`)
- Test: extend `test_warroom.py`, `test_lenses.py` (assert the block appears in the
  prompt when policies exist; assert graceful when empty)

**Design:** a tiny helper (e.g. `context_feed.augment(system_or_user, block)`) so every
call site injects identically. Keep the degrade rule: no active outcomes → prompts
unchanged; context-feed failure → prompt without context, never a crash.

**Steps:** failing test → implement → pass → commit
`feat(phase3): feed durable outcomes into war-room + lens prompts`

### Task 5: Outcomes ledger view wired to real data

**Objective:** Replace the mockup's static Outcomes fixtures with real rows + real
summary-strip counts (mirrors the Phase 0 Inbox wiring). (Depends on Q5.)

**Files:**
- Modify: `pmqs/pmqs/web/render.py` (`render_outcomes(...)` splicing into the mockup's
  Outcomes view; update summary counts)
- Modify: `pmqs/pmqs/api/outcomes.py` (serve the rendered Outcomes page; deactivate
  action)
- Test: `pmqs/tests/test_render_outcomes.py`

**Steps:** failing test → implement → pass → commit
`feat(phase3): wire Outcomes ledger view to real rows`

### Task 6: End-to-end Phase 3 verification (real LLM, real repo)

**Objective:** Prove the loop: create a Policy in a war-room → it appears in the ledger →
a NEW war-room session's LLM reply visibly reflects that policy (the eat-its-own-cooking
moment) → Issue outcome still round-trips to GitHub → policy never leaves the hosted
store.

**Steps:** scripted + manual, mirroring Phase 1/2 verification. Full `pytest -q` green.
Close any seed issues; leave repo clean. Commit `test(phase3): end-to-end context-feed`.

---

## Files likely to change (summary)

- Create: `outcomes/types.py`, `context_feed.py`, `tests/test_outcome_types.py`,
  `tests/test_outcome_lifecycle.py`, `tests/test_context_feed.py`,
  `tests/test_render_outcomes.py`.
- Modify: `models.py` (outcomes.active), `repository.py` (durable-outcome queries),
  `api/outcomes.py` (typed create + ledger page + deactivate), `warroom.py`, `lenses.py`
  (context injection; maybe `framing.py`/`position_doc.py` per Q2), `web/render.py`
  (render_outcomes), `config.py`/settings (context budget per Q6).

## Risks / tradeoffs

- **Cost creep.** Injecting context grows every prompt. Mitigation: char budget (Q6),
  Q1=all-active (no extra LLM call), and confining injection to chosen call sites (Q2).
- **Policy leakage to GitHub.** More code touches policies now. Mitigation: keep the
  `create_outcome` guard, add an explicit context-feed test that a policy is never in
  any GitHub-bound payload, and never route durable outcomes through the Issue path.
- **Context staleness.** Old policies distorting new sessions. Mitigation: the
  deactivate/active lifecycle (Task 2) so the PM can retire a policy.
- **Ledger render fragility.** Same splice-by-anchor approach as Inbox/Workspace; a
  render test guards the mockup anchors.

## Verification checklist

- [ ] All new tests pass with `PMQS_LLM_MODE=off` (offline/deterministic).
- [ ] Real e2e: a Policy created in one session influences a later session's reply.
- [ ] `test_no_hazard.py` passes; no policy ever reaches a GitHub-bound payload.
- [ ] Inbox / Workspace / Settings unregressed.
- [ ] Context-feed reuses one mechanism for all non-Issue types (no per-type bespoke).
