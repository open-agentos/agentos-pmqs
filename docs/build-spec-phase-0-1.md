# PMQs — Build Spec: Phase 0 → Phase 1

Read `product-design.md` and `architecture.md` first — this doc assumes both as given
and does not re-explain rationale. This spec covers Phase 0, Phase 0.5, and Phase 1
in full task-level detail, with a short Phase 2 preview at the end. Do not implement
Phase 2 behavior against this spec — it will be re-spec'd once Phase 1 is running.

**Hard rule, non-negotiable:** never run `agentos apply` or `agentos upgrade` against
`agentos-pmqs`. See `architecture.md` for why.

## Stack decisions (assumed, confirmed by product owner)

- Backend: Python, FastAPI.
- AgentOS integration: via CLI subprocess (`agentos state --json`, etc.), not an
  importable Python API. If a stable importable API is discovered during Phase 0,
  flag it — this is worth revisiting, but don't block on it.
- Persistence (Phase 0.5+): SQLite. Use SQLAlchemy Core or ORM so a later swap to
  Postgres (Phase 5) doesn't require a rewrite.
- Frontend: serve backend-rendered HTML reusing `pmqs-mockup.html`'s CSS/markup
  directly (its `#app`/`#rail`/`#main` structure, view-switching JS, and card/pill/
  ledger components already match the Inbox/Workspace/Outcomes shells). Phase 0's
  render task is templating real data into that existing structure, not building a
  new frontend. A framework migration (React, etc.) is a later-phase call, not a
  Phase 0/1 blocker.

## Repo layout

```
pmqs/
  docs/
    product-design.md
    architecture.md
    build-spec-phase-0-1.md
    pmqs-mockup.html          # visual/interaction reference — reuse its CSS/markup
  pmqs/                      # python package
    __init__.py
    agentos_client.py        # CLI subprocess wrapper
    models.py                # SQLAlchemy models: Question, Outcome, Session
    db.py                    # engine/session setup
    triggers/
      __init__.py
      base.py                # Trigger protocol
      stale_issue_age.py     # quality/reliability lens
      label_conflicts.py     # risk/exposure lens
    scoring.py                # unified scoring formula
    dedup.py                  # LLM dedup/collision pass
    framing.py                 # LLM framing pass ("why this matters")
    outcomes/
      __init__.py
      issue.py                # push-to-GitHub action
    api/
      __init__.py
      inbox.py                 # FastAPI routes: list/score/filter/quick-add
      outcomes.py               # FastAPI routes: ledger + push action
    web/                        # templates or frontend build, TBD per above
  tests/
    test_triggers.py
    test_scoring.py
    test_dedup.py
    test_outcomes_issue.py
  pyproject.toml
  README.md                    # must state the apply/upgrade hazard prominently
```

---

## Phase 0 — Single-tenant, no-auth, dogfooded, read-only

**Goal:** prove the read/render loop against real `agentos-pmqs` data. No writes,
no persistence.

### Tasks

1. **Repo scaffold.** Create the layout above. `README.md` must open with the
   apply/upgrade hazard warning — this is not optional boilerplate.
2. **`agentos_client.py`.** A thin wrapper around `subprocess.run(["agentos", "state",
   "--json"], cwd=<agentos-pmqs path>)` that parses the JSON output into plain Python
   dicts. No retries/caching needed yet — keep it dumb.
   - *Acceptance:* calling `get_state()` against a real `agentos-pmqs` checkout
     returns parsed JSON without error.
3. **Minimal render.** A single FastAPI route (`GET /`) that calls `agentos_client`,
   maps raw Issues/Labels into a flat list of dicts shaped like a future `Question`
   (title, description placeholder, evidence pointer = issue URL), and renders them
   into `pmqs-mockup.html`'s Inbox `.card` markup in place of its hardcoded fixture
   cards (view-switching JS, Workspace, and Outcomes can stay exactly as-is/static in
   Phase 0 — Inbox is the one that needs real data wired in).
   - *Acceptance:* running the app locally and hitting `/` shows the same visual
     Inbox as the mockup, but populated with real Issues from `agentos-pmqs` instead
     of the mockup's fixture cards (the #47 mitigation card, the PR #55/#56 card,
     etc.).
4. **No `agentos apply`/`upgrade` calls anywhere in the codebase.** Grep for these
   strings in CI or pre-commit if convenient — cheap insurance against the hazard.

### Phase 0 exit criterion

You can open PMQs locally and see a real, if crude, Inbox rendered from
`agentos-pmqs`'s actual Issues/Labels.

---

## Phase 0.5 — Fake the hosted store

**Goal:** give Questions and Outcomes somewhere to live that survives a restart.

### Schema

```sql
CREATE TABLE questions (
  id            TEXT PRIMARY KEY,          -- uuid
  title         TEXT NOT NULL,
  description   TEXT,                       -- fuller explanation, dedup reasoning,
                                             -- raw LLM thinking, source links
  lens_tags     TEXT NOT NULL,               -- JSON array, e.g. ["quality_reliability"]
  evidence      TEXT NOT NULL,               -- JSON array of {type, ref, url}
  score         REAL,                        -- unified scoring output, nullable until scored
  score_dims    TEXT,                        -- JSON object of per-dimension scores
  status        TEXT NOT NULL DEFAULT 'proposed',
                                             -- proposed | saved | dismissed | promoted
  source        TEXT NOT NULL,               -- 'system' | 'pm'
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE sessions (
  id            TEXT PRIMARY KEY,
  topic         TEXT,
  question_id   TEXT REFERENCES questions(id),   -- nullable, session may not start from a Question
  status        TEXT NOT NULL DEFAULT 'open',     -- open | closed
  created_at    TEXT NOT NULL,
  closed_at     TEXT
);

CREATE TABLE outcomes (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,               -- 'issue' | 'policy' | 'document' | 'meeting' | 'question'
  session_id    TEXT REFERENCES sessions(id),
  payload       TEXT NOT NULL,               -- JSON, shape depends on type
  github_ref    TEXT,                        -- populated only for type='issue' after push
  created_at    TEXT NOT NULL
);
```

Notes:
- `outcomes.payload` is deliberately a JSON blob with a type discriminator rather than
  per-type tables — no real schema pressure yet on Policy/Document/Meeting, per the
  product record. Revisit if Phase 3 needs it.
- Policies must never reference or sync to GitHub — confirm no code path writes
  `outcomes` rows of type `policy` to `github_ref`.

### Tasks

1. `db.py` — SQLAlchemy engine against a local SQLite file, session factory.
2. `models.py` — ORM models matching the schema above.
3. Wire Phase 0's render path to read from `questions` instead of live AgentOS calls
   directly (AgentOS calls now populate `questions` rather than being rendered
   straight through).
4. Basic CRUD: create/read/update Question status, create Outcome.

### Phase 0.5 exit criterion

Questions and Outcomes survive a process restart. A manually-inserted Question shows
up in the Inbox render.

---

## Phase 1 — Repo evidence only, Issue outcome only

This is the first phase with real product behavior. Sub-tracks below can proceed
somewhat in parallel once Phase 0.5's schema is in place.

### 1. Structural triggers

Implement 2–3 triggers to start — not all 8 lenses. Recommended starting set:

- `stale_issue_age.py` (quality/reliability lens): flags Issues open past a
  configurable age threshold with no activity.
- `label_conflicts.py` (risk/exposure lens): flags Issues with contradictory labels
  (define the specific conflict pairs when you get here — not fixed by this spec).

Each trigger:
- Is a scheduled, deterministic query against Issues/Labels/PRs/Actions via
  `agentos_client`.
- Writes a `questions` row directly — `status='proposed'`, `source='system'`,
  `evidence` populated with the triggering Issue/PR/run reference. No LLM call inside
  the trigger itself.
- *Acceptance:* given a fixture `agentos-pmqs` state with a known stale issue, the
  trigger produces exactly one Question row referencing it.

### 2. LLM framing pass (`framing.py`)

- Runs *after* a structural trigger fires, as a separate step — takes a trigger's
  raw hit and produces the human-readable `title`/`description` for the Question.
  Keep this decoupled from the trigger so the trigger stays swappable/deterministic.
- *Acceptance:* given a trigger hit fixture, produces a non-empty title and
  description; failure to call the LLM does not crash the trigger pipeline (trigger
  hit should still produce a Question, even with a degraded/fallback description).

### 3. Dedup pass (`dedup.py`)

- LLM judgment call: given the day's batch of candidate Questions, identifies pairs/
  groups that are really about the same underlying thing and merges them (merge
  reasoning goes into the surviving Question's `description`).
- *Acceptance:* given two fixture Questions that are near-duplicates, dedup reduces
  them to one; given two genuinely distinct Questions, both survive.

### 4. Unified scoring (`scoring.py`)

- One function, one formula: takes a Question (any status) and returns a score plus
  per-dimension breakdown. Lens weight is one input dimension among several — no
  separate code path for `status='saved'` Questions.
- Per-product lens weight defaults live in config (simple dict/JSON is fine for
  Phase 1 — no settings UI required yet).
- *Acceptance:* scoring is a pure function of a Question + config — same inputs,
  same output. Saved and proposed Questions run through the identical formula.

### 5. Inbox UI

- Ranked list ordered by score.
- Quiet filter selector (not a heavy dropdown) — filter by lens tag at minimum.
- Quick-add: a form/endpoint that creates a `source='pm'` Question directly.
- Saved items rendered in the same list, visually distinct (e.g. a subtle marker),
  not a separate section.
- *Acceptance:* a PM-added Question appears in the ranked list alongside
  system-generated ones, scored by the same formula.

### 6. Issue outcome — push to GitHub (`outcomes/issue.py`)

- Action on a Question: creates a real GitHub Issue in `agentos-pmqs` via the CLI
  (not the full shared-credentials/App-installation flow — out of scope for MVP).
- On success: writes an `outcomes` row (`type='issue'`, `github_ref` = created
  Issue URL/number), updates the source Question's `status='promoted'`.
- *Acceptance:* pushing a real Question from the Phase 1 build creates a real,
  visible Issue in `agentos-pmqs`, and the Outcomes table has a matching row.

### Phase 1 exit criterion

A real day's worth of structural-trigger Questions show up ranked in the Inbox, and
at least one gets pushed to a real GitHub Issue in `agentos-pmqs`, with the round
trip reflected in the `outcomes` table.

---

## Phase 2 preview (do not build yet)

Once Phase 1 is running and its actual shape is known, Phase 2 adds: the war-room
Workspace shell (multi-pane, session-branching), on-demand Position Document
generation (Voter Guide format), and the full 8-lens LLM triager for session-scoped
research (as opposed to Phase 1's 2–3 always-on structural triggers). Expect the
scoring/dedup logic built in Phase 1 to be reused, not replaced, by the session-scoped
lens pass. Do not pre-build Workspace UI or Position Document generation against this
spec — it needs its own build spec once Phase 1's real behavior is observed.
