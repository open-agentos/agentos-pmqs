# PMQs — Build Spec: Phase 2 (War-room Workspace, Position Documents, 8-Lens Triager)

> **For Hermes:** Use the `subagent-driven-development` skill to implement this plan
> task-by-task, with two-stage review (spec compliance, then code quality) per task.

**Goal:** Turn the Workspace mode from a static mockup shell into a working war-room:
open a session on a Question, converse with an LLM that probes the PM's thinking,
generate an on-demand Position Document (Voter Guide format), run a fresh session-scoped
8-lens interpretive triager, and produce typed Outcomes — reusing the Phase 1 scoring,
dedup, framing, LLM, and outcome plumbing rather than replacing it.

**Architecture:** Same shape as Phase 0/1. FastAPI backend renders real data into the
existing `pmqs-mockup.html` Workspace markup (conversation pane + 4 artifact tabs +
outcome bar), exactly as Phase 0 did for the Inbox. Sessions and their messages persist
in SQLite (the `sessions` table already exists; add a `session_messages` table).
Position Documents and the 8-lens pass are new LLM modules that reuse `pmqs/llm.py`.
Every LLM path keeps the Phase 1 rule: failure degrades gracefully, never crashes.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (SQLite), LiteLLM via `pmqs/llm.py`,
server-rendered HTML reusing the mockup. No new frontend framework.

**Status of prerequisites (observed from the running Phase 1 build):**
- Inbox render, triggers, scoring, framing, dedup, Issue outcome, and the LLM client
  are all working and committed (baseline `3028368`, LLM wiring `49497cb`).
- `sessions` and `outcomes` tables exist; `outcomes.payload` is a typed JSON blob.
- The mockup already contains the full Workspace markup — this is a wiring job.

**Hard rule (unchanged):** never run `agentos apply`/`agentos upgrade` against
`agentos-pmqs`. The `test_no_hazard.py` guard must keep passing.

---

## Scope boundaries

**In scope (Phase 2):**
1. War-room Workspace shell wired to real sessions + conversation (multi-pane).
2. Session branching (a session can spawn child sessions / new questions).
3. On-demand Position Document generation in Voter Guide format.
4. Session-scoped 8-lens interpretive triager (the full LLM lens pass).
5. Wiring the artifact tabs (Position document, Evidence, Impacts, Proposed questions).
6. Typed Outcomes beyond Issue at the Workspace outcome bar — BUT see the note below.

**Out of scope (later phases, do NOT build):**
- Policy/Document/Meeting outcome *storage semantics* beyond a JSON row (Phase 3 owns
  the real per-type behavior and the unified context-feed mechanism). Phase 2 may write
  the `outcomes` rows (type + payload) so the outcome bar works, but must NOT build
  per-type integrations, and must NOT ever push a `policy` row to GitHub.
- News ingestion / interpretive news lens (Phase 4).
- Auth / multi-tenant (Phase 5).
- Any framework migration.

**Open questions — RESOLVED by product owner (2026-07-13):**
- Q1 (8-lens trigger): **Explicit "Run lenses" button**, not auto-on-open. Prioritize
  conserving tokens over seamless UX. No auto-run, no per-open LLM cost.
- Q2 (Position Document caching): **Generate once, on demand, persist indefinitely.** No
  regenerate button. Once a session has a Position Document, it is fixed.
- Q3 (model for expensive passes): Introduce a **Settings panel** (new surface). Its
  first section configures the LLM provider, API key, and model. **Default: Anthropic
  Haiku** (`anthropic/claude-haiku-4-5-20251001`). Settings are read by `pmqs/llm.py`.

---

## Data model additions

### Task 0: Add `session_messages` table + Session helpers

**Objective:** Persist war-room conversation turns and link child sessions.

**Files:**
- Modify: `pmqs/pmqs/models.py`
- Modify: `pmqs/pmqs/repository.py`
- Test: `pmqs/tests/test_sessions.py` (create)

**Step 1: Write failing test** (`pmqs/tests/test_sessions.py`)

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pmqs.db import Base
from pmqs import repository


def _db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_open_session_and_add_messages():
    db = _db()
    q = repository.create_question(db, title="root q", source="system")
    s = repository.open_session(db, topic="war-room", question_id=q.id)
    repository.add_message(db, s.id, role="system", content="probe")
    repository.add_message(db, s.id, role="pm", content="answer")
    msgs = repository.list_messages(db, s.id)
    assert [m.role for m in msgs] == ["system", "pm"]


def test_session_branching():
    db = _db()
    parent = repository.open_session(db, topic="parent")
    child = repository.open_session(db, topic="child", parent_id=parent.id)
    assert child.parent_id == parent.id
```

**Step 2: Run** `pytest tests/test_sessions.py -v` → expect FAIL (no `session_messages`,
no `open_session`/`add_message`/`list_messages`, no `parent_id`).

**Step 3: Add model + `parent_id` column** (`pmqs/pmqs/models.py`)

```python
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    topic: Mapped[str | None] = mapped_column(Text)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))  # branching
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    closed_at: Mapped[str | None] = mapped_column(Text)


class SessionMessage(Base):
    __tablename__ = "session_messages"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # system | pm | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
```

**Step 4: Add repository helpers** (`pmqs/pmqs/repository.py`)

```python
def open_session(db, *, topic=None, question_id=None, parent_id=None):
    s = Session(topic=topic, question_id=question_id, parent_id=parent_id, status="open")
    db.add(s); db.commit(); return s

def add_message(db, session_id, *, role, content):
    m = SessionMessage(session_id=session_id, role=role, content=content)
    db.add(m); db.commit(); return m

def list_messages(db, session_id):
    from sqlalchemy import select
    return list(db.scalars(select(SessionMessage)
        .where(SessionMessage.session_id == session_id)
        .order_by(SessionMessage.created_at)))

def close_session(db, session_id):
    s = db.get(Session, session_id)
    if s: s.status = "closed"; s.closed_at = _now(); db.commit()
    return s
```

**Step 5: Run** `pytest tests/test_sessions.py -v` → expect PASS.

**Step 6: Commit** `feat(phase2): session_messages table + branching + session CRUD`

---

## Settings

### Task 0.5: Settings store + Settings panel (LLM section)

**Objective:** A persistent Settings surface. First section: LLM provider, API key, and
model. Built to extend later (lens weights, thresholds, etc. are future sections).
`pmqs/llm.py` reads the stored LLM settings, overriding env/Hermes resolution when set.

**Files:**
- Modify: `pmqs/pmqs/models.py` (add `Setting` key/value table)
- Create: `pmqs/pmqs/settings.py` (typed get/set over the table; LLM settings accessor)
- Modify: `pmqs/pmqs/llm.py` (resolution precedence: Settings > env > Hermes)
- Create: `pmqs/pmqs/api/settings.py` (GET settings page + POST save)
- Modify: `pmqs/pmqs/web/render.py` (render a simple Settings view; reuse mockup CSS)
- Modify: `pmqs/pmqs/api/app.py` (include router)
- Test: `pmqs/tests/test_settings.py`

**Design:**
- `Setting(key TEXT PRIMARY KEY, value TEXT)` — a plain key/value table (JSON values).
  YAGNI: no per-section tables yet.
- `settings.get_llm() -> {provider, model, api_key_ref}` with defaults:
  `provider='anthropic'`, `model='anthropic/claude-haiku-4-5-20251001'`.
- **API key handling:** do NOT store raw keys in the DB in plaintext as the primary
  path. Store a *reference* to an env var name (e.g. `ANTHROPIC_API_KEY`), consistent
  with the Hermes pattern already in `llm.py`. Allow a raw key entry too, but if entered,
  keep it out of the mockup HTML render (never echo a stored key back into the page —
  show a masked placeholder). This keeps the prototype secure-by-default (matches the
  product owner's security preference).
- **`llm.py` precedence:** if Settings has an LLM config, use it; else fall back to the
  existing `PMQS_LLM_MODE` env / Hermes resolution. Default resolves to Anthropic Haiku.

**Step 1: failing test** (`pmqs/tests/test_settings.py`)

```python
from pmqs import settings

def test_llm_defaults_to_anthropic_haiku(db):
    cfg = settings.get_llm(db)
    assert cfg["provider"] == "anthropic"
    assert "haiku" in cfg["model"]

def test_set_and_get_llm(db):
    settings.set_llm(db, provider="anthropic", model="anthropic/claude-fable-5",
                     api_key_ref="ANTHROPIC_API_KEY")
    cfg = settings.get_llm(db)
    assert cfg["model"] == "anthropic/claude-fable-5"

def test_raw_key_never_rendered(db):
    settings.set_llm(db, provider="anthropic", model="m", api_key_raw="sk-secret")
    from pmqs.web.render import render_settings
    html = render_settings(db)
    assert "sk-secret" not in html  # masked
```

**Step 2: Run** `pytest tests/test_settings.py -v` → expect FAIL.

**Step 3–4: Implement** `Setting` model, `settings.py`, `render_settings`, wire `llm.py`
precedence. Run tests → PASS.

**Step 5: Manual check** — GET `/settings` renders the LLM section with the current
model shown and the key masked; POST saves; a subsequent framing call uses the saved
model.

**Step 6: Commit** `feat(phase2): Settings store + panel (LLM provider/model section)`

---

## War-room conversation

### Task 1: War-room conversation engine (`pmqs/warroom.py`)

**Objective:** A decision-oriented conversational loop that probes the PM's thinking
(not adversarial counter-argument theater, per product-design.md).

**Files:**
- Create: `pmqs/pmqs/warroom.py`
- Test: `pmqs/tests/test_warroom.py`

**Design:** `respond(db, session_id, pm_message)` appends the PM message, builds an LLM
prompt from (a) the session's originating Question + evidence, (b) prior messages, and
(c) a system prompt that instructs "probe and challenge the PM's reasoning, surface
what's actually true before they decide, do not argue for argument's sake." Persists
and returns the assistant message. LLM failure → a graceful fallback message, session
intact (reuse the Phase 1 fallback discipline).

**Step 1: failing test** — inject a stub `warroom.llm.complete` that echoes; assert an
assistant message is persisted and returned, and that a raised exception yields a
fallback assistant message rather than propagating.

**Steps 2–5:** implement minimal loop, run tests.

**Step 6: Commit** `feat(phase2): war-room conversation engine with probe prompt`

---

### Task 2: 8-lens session-scoped triager (`pmqs/lenses.py`)

**Objective:** On a session topic, run the full interpretive 8-lens pass that assembles
multiple points of view (feeds session framing AND proposed-questions), reusing Phase 1
`scoring.py` and `dedup.py` — not a parallel system.

**Files:**
- Create: `pmqs/pmqs/lenses.py` (the 8 lenses from product-design.md as prompt specs)
- Modify: `pmqs/pmqs/config.py` (lens list already has weights; add lens descriptions)
- Test: `pmqs/tests/test_lenses.py`

**Design:** `run_session_lenses(db, session)` → for the session topic + evidence, an LLM
triages which of the 8 lenses are relevant (LLM judgment, per spec — not hardcoded
topic→lens mapping), then for each relevant lens produces candidate Questions. Feed the
batch through existing `dedup.dedup(...)`, score with existing `scoring.score_question`,
persist as `status='proposed'`, `source='system'`, tagged with the session. These are
the "Proposed questions" artifact-tab items.

**Cost control (per resolved Q1):** this pass runs ONLY when the PM clicks "Run lenses"
in the Workspace — never automatically on session open. It is the single most expensive
action in the product; make it explicit and idempotent-friendly (a second click
re-runs; that's the PM's choice). Uses the model configured in Settings (Anthropic Haiku
default).

**Reuse (do not duplicate):** `dedup`, `scoring`, `framing`, `llm`. The 8-lens taxonomy
already exists in `config.LENS_WEIGHTS`.

**Step 1: failing test** — stub the LLM to return a fixed relevant-lens set + candidates;
assert proposed Questions are persisted, deduped, and scored by the SAME formula as
Phase 1 (compare against a direct `scoring.score_question` call).

**Steps 2–5:** implement, run.

**Step 6: Commit** `feat(phase2): session-scoped 8-lens interpretive triager`

---

### Task 3: Position Document generator (`pmqs/position_doc.py`)

**Objective:** On-demand, Voter-Guide-format research report for a Question/decision.

**Files:**
- Create: `pmqs/pmqs/position_doc.py`
- Test: `pmqs/tests/test_position_doc.py`

**Voter Guide structure (from product-design.md) — the generator must produce all of:**
1. Plain-language summary.
2. "What your vote means" — yes/no consequence framing.
3. Neutral analyst background / fiscal-(cost-)impact section.
4. Argument FOR + rebuttal.
5. Argument AGAINST + rebuttal.

**Design:** `generate(db, question) -> dict` with those five sections, grounded in the
Question's evidence (exhaustive evidence-promotion pass on demand, per spec).

**Persistence (per resolved Q2):** generate ONCE, on demand, and persist INDEFINITELY.
Add a `position_doc TEXT` (JSON) column to `sessions`. There is NO regenerate button:
if `session.position_doc` is already set, the "Generate Position Document" action is a
no-op that just displays the stored doc. This caps Position Document cost at exactly one
LLM call per session, ever. Uses the Settings model (Anthropic Haiku default).

**Step 1: failing test** — stub LLM to return the five sections; assert all five present,
non-empty, and that evidence refs from the Question appear in the doc payload. Assert LLM
failure returns a clearly-marked fallback doc rather than crashing.

**Steps 2–5:** implement, run.

**Step 6: Commit** `feat(phase2): on-demand Voter-Guide Position Document generator`

---

## Workspace UI wiring

### Task 4: Render real Workspace from a session

**Objective:** Replace the mockup's hardcoded Workspace fixtures with real session data,
exactly as `web/render.py` did for the Inbox (splice into existing markup, keep CSS/JS).

**Files:**
- Modify: `pmqs/pmqs/web/render.py` (add `render_workspace(session, ...)`)
- Test: `pmqs/tests/test_render_workspace.py`

**Wire these mockup regions (by their existing anchors):**
- `.convo-scroll` (line ~410): real `session_messages` as `.msg system|pm` bubbles.
- `#tab-doc` (line ~439): the Position Document sections (or a "Generate" prompt if none).
- `#tab-evidence` (line ~480): the Question's evidence list as `.evidence-item`s.
- `#tab-proposed` (line ~495): the 8-lens proposed Questions as `.proposed-item`s with
  the existing "+ Add to inbox" / "Dismiss" actions.
- `.session-stats` (line ~526): real exchange count / cost / time for the session.
- `#tab-chart` (Impacts, line ~467): leave static in Phase 2 unless cheap; flag as
  Phase 3+ (Impacts needs cost telemetry not yet modeled). Do NOT invent numbers.

**Step 1: failing test** — build a session with 2 messages + 1 proposed question, call
`render_workspace`, assert the returned HTML contains the real message text and the
proposed-question title, and that `view-inbox`/`view-outcomes` markup is preserved.

**Steps 2–5:** implement the splice (same regex-anchor approach as `render_inbox`), run.

**Step 6: Commit** `feat(phase2): render real war-room Workspace into mockup shell`

---

### Task 5: Workspace API routes (`pmqs/api/workspace.py`)

**Objective:** Endpoints backing the Workspace interactions.

**Files:**
- Create: `pmqs/pmqs/api/workspace.py`
- Modify: `pmqs/pmqs/api/app.py` (include router)
- Test: `pmqs/tests/test_api_workspace.py` (use FastAPI TestClient, stub LLM off)

**Routes:**
- `POST /workspace/open` (question_id?) → open a session, redirect to the workspace view.
  Does NOT auto-run lenses (per resolved Q1 — that's an explicit action below).
- `GET  /workspace/{session_id}` → `render_workspace(...)`.
- `POST /workspace/{session_id}/message` (Form: content) → `warroom.respond`, redirect.
- `POST /workspace/{session_id}/run-lenses` → `lenses.run_session_lenses(...)`, redirect.
  This is the ONLY entry point to the expensive 8-lens pass; UI is a "Run lenses" button.
- `POST /workspace/{session_id}/position-doc` → if `session.position_doc` unset,
  `position_doc.generate` + persist; if already set, no-op (per resolved Q2 — generate
  once, no regenerate). Redirect to the doc tab.
- `POST /workspace/{session_id}/branch` (topic) → child session (branching).
- `POST /workspace/{session_id}/proposed/{qid}/add` → flip proposed Question into the
  Inbox (status stays proposed; it already shows — this just marks it PM-acknowledged).
- Reuse existing `POST /questions/{qid}/push-issue` for the Issue outcome from a session.

**Step 1: failing test** — TestClient: open a session (LLM off → lens fallback), GET the
workspace returns 200 with the shell, POST a message returns 303 and persists it.

**Steps 2–5:** implement, run.

**Step 6: Commit** `feat(phase2): Workspace API routes (open/message/position-doc/branch)`

---

### Task 6: Typed outcomes at the outcome bar (Issue real; others row-only)

**Objective:** Wire the outcome bar buttons to create `outcomes` rows, respecting the
Phase 3 boundary and the policy-never-to-GitHub rule.

**Files:**
- Modify: `pmqs/pmqs/api/outcomes.py`
- Test: extend `pmqs/tests/test_outcomes_issue.py`

**Design:** `POST /workspace/{session_id}/outcome` (Form: type, payload). For `issue`,
call the existing `push_question_to_issue` path when tied to a Question, else create the
Issue from the session summary. For `policy|document|meeting|question`, write an
`outcomes` row (JSON payload, `session_id` set, `github_ref=None`). Enforce (already in
`repository.create_outcome`) that a `policy` never gets a `github_ref`. Do NOT build the
per-type context-feed — that's Phase 3.

**Step 1: failing test** — creating a `policy` outcome with a github_ref raises; a
`document` outcome persists with `session_id` and no github_ref; an `issue` outcome tied
to a Question promotes it (reuse existing assertions).

**Steps 2–5:** implement, run.

**Step 6: Commit** `feat(phase2): typed outcomes from the war-room outcome bar`

---

## Integration & verification

### Task 7: End-to-end Phase 2 verification (real LLM, real repo)

**Objective:** Prove the Phase 2 exit criterion against real data.

**Steps (manual + scripted, mirroring the Phase 0/1 verification):**
1. Seed 2–3 real open issues in `open-agentos/agentos-pmqs` (as in Phase 1).
2. Run the Phase 1 pipeline to populate the Inbox.
3. Open a war-room session on the top-ranked Question (`PMQS_LLM_MODE=hermes`).
4. Confirm: the 8-lens pass produced proposed Questions (scored by the Phase 1 formula);
   a PM message gets a probing LLM reply; a Position Document generates with all five
   Voter-Guide sections; an Issue outcome pushes to real GitHub and lands in `outcomes`.
5. Confirm the Inbox and Outcomes views still render (no regression).
6. Run full suite: `pytest -q` → all green (Phase 0/1 tests + new Phase 2 tests).
7. Close the seed issues.

**Exit criterion (Phase 2):** A PM can open a real Question into a war-room, be
meaningfully probed, see a fresh 8-lens set of proposed questions, generate a
Voter-Guide Position Document on demand, and produce at least one typed Outcome — with
Issue outcomes round-tripping to real GitHub — all rendered in the existing mockup shell.

**Step: Commit** `test(phase2): end-to-end war-room verification + docs`

---

## Files likely to change (summary)

- Create: `settings.py`, `warroom.py`, `lenses.py`, `position_doc.py`,
  `api/settings.py`, `api/workspace.py`, `tests/test_sessions.py`,
  `tests/test_settings.py`, `tests/test_warroom.py`, `tests/test_lenses.py`,
  `tests/test_position_doc.py`, `tests/test_render_workspace.py`,
  `tests/test_api_workspace.py`.
- Modify: `models.py` (session_messages + parent_id + session.position_doc + Setting
  table), `repository.py` (session/message CRUD), `settings.py` accessors,
  `llm.py` (Settings > env > Hermes precedence, Anthropic Haiku default),
  `web/render.py` (render_workspace + render_settings), `api/app.py` (routers),
  `api/outcomes.py` (typed outcomes), `config.py` (lens descriptions).

## Risks / tradeoffs

- **Cost.** The 8-lens pass + Position Documents are the most expensive LLM calls in the
  product so far. Mitigations: auto-run gated by a config flag (Open Q Q1), Position Docs
  on-demand + cached (Open Q Q2), per-pass model override (Open Q Q3). Keep the
  degrade-gracefully rule so a budget/credential failure never breaks a session.
- **Scope creep into Phase 3.** The outcome bar makes all five types tempting to fully
  build. Hold the line: rows only for non-Issue types; no context-feed, no per-type
  integration.
- **Render fragility.** `render_workspace` uses the same splice-by-anchor approach as
  `render_inbox`; if the mockup markup changes, anchors must be updated. A render test
  guards this.
- **Impacts tab.** Needs cost telemetry that isn't modeled yet. Left static and flagged
  rather than fabricated.

## Verification checklist

- [ ] All new tests pass with `PMQS_LLM_MODE=off` (deterministic/offline).
- [ ] Real end-to-end run under `PMQS_LLM_MODE=hermes` (Task 7).
- [ ] `test_no_hazard.py` still passes (no apply/upgrade).
- [ ] Inbox + Outcomes views unregressed.
- [ ] Scoring/dedup/framing reused, not reimplemented.
- [ ] No `policy` outcome ever carries a `github_ref`.
