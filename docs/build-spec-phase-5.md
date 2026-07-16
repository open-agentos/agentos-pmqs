# PMQs — Build Spec: Phase 5 (Auth + Multi-Tenant + Hosted)

> **For Hermes:** Use the `subagent-driven-development` skill to implement this plan
> task-by-task, with two-stage review per task.
> **Do not implement until the product owner has answered the OPEN QUESTIONS below.**
> This is the largest phase so far — it touches every table (tenant scoping), every
> route (auth gate + workspace resolution), and the persistence layer. Expect it to be
> broken into several sub-milestones; the open questions decide how big each is.

**Goal:** Turn the single-tenant, no-auth dogfood app into a **hosted, multi-tenant**
product: a PM logs in, lands in their own **workspace**, and sees only their workspace's
questions/sessions/outcomes/settings. One codebase, pluggable deployment (the
Figma/Notion/Linear cloud+self-host split from product-design.md). Google Auth is
**login-only** — never a write-scope dependency for any outcome.

**Architecture reality (from the current code):** Everything is single-tenant today —
six tables (`questions`, `sessions`, `session_messages`, `settings`, `news_items`,
`outcomes`) with NO tenant column; `settings` is a global key/value store; the DB is one
local SQLite file; every route reads/writes global state with no identity. Phase 5
introduces a **Workspace** as the tenant boundary, scopes every table + query to it,
gates every route behind auth, and resolves the current workspace per request.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy. Persistence may move SQLite→Postgres
(see Q2). Auth via OAuth2 (Google) + session cookies (see Q1). Server-rendered HTML
unchanged in shape; a login page + workspace switcher added.

**Prerequisites (done, remote `main` @ 68d1ee5):** Phases 0–4 — full Inbox/war-room/
outcomes/news loop, Settings, context-feed. All 95 tests green, single-tenant.

**Hard rules (unchanged):** never `agentos apply`/`upgrade`; policies never to GitHub;
raw news never to GitHub. **NEW invariant:** no cross-tenant data access — every query
is workspace-scoped; a test must prove workspace A cannot see workspace B's rows.

---

## The core challenge: tenant scoping without a rewrite

Multi-tenant means a **Workspace** (tenant) owns all data. Two structural changes ripple
everywhere:

1. **Data model:** add `Workspace` + `User` tables; add `workspace_id` FK to all six
   existing tables; make `settings` per-workspace (composite key `(workspace_id, key)`).
2. **Request path:** authenticate → resolve the user's workspace → pass `workspace_id`
   into every repository call. The cleanest approach is a request-scoped "current
   workspace" dependency that repository functions require, so a missing scope is a
   loud error, not a silent global read. Every existing `repository.*` signature gains a
   `workspace_id` (or a scoped session wrapper). This is the bulk of the work.

Because this is invasive, the migration is staged: introduce the tenant column with a
default "personal" workspace (so existing dogfood data keeps working), backfill, then
enforce scoping everywhere, then add auth on top.

---

## OPEN QUESTIONS — need product-owner answers before building

**Q1 — Auth mechanism.** product-design.md says Google Auth, login-only. Options:
  - (a) **Real Google OAuth2** (Authlib) + signed session cookie. Production-shaped, but
    needs a Google OAuth client ID/secret configured (another Settings/env secret) and a
    redirect URL — more setup, harder to test offline.
  - (b) **Pluggable auth with a dev/local provider now + Google OAuth behind the same
    interface.** Ship an `AuthProvider` abstraction: a `local` provider (email-only,
    no password — fine for self-host/dev) as the default, and a `google` provider that
    drops in when OAuth creds are configured. Matches the "one codebase, pluggable
    auth/deployment" positioning and keeps tests offline.
  - (c) Google OAuth only, no local option.
  My lean: **(b)** — pluggable, `local` default, `google` when configured. It's the
  literal product positioning and keeps the prototype runnable/testable without Google
  creds. Confirm.

**Q2 — Persistence: SQLite vs Postgres, now?** The code was written "SQLAlchemy so a swap
  is easy." Options:
  - (a) **Stay on SQLite for Phase 5**, just add tenant scoping + auth. Postgres is a
    deploy-time swap (`DATABASE_URL`) validated later. Cheapest; multi-tenant works fine
    on SQLite for a prototype.
  - (b) **Move to Postgres now** as part of Phase 5 (real hosted DB, connection via
    `DATABASE_URL`, docker-compose for local Postgres).
  My lean: **(a)** — do tenant scoping + auth on SQLite (the hard product logic), make
  the engine `DATABASE_URL`-driven so Postgres is a config flip, and defer actually
  standing up Postgres to the hosting step. Avoids conflating two big changes. Confirm.

**Q3 — Tenant model shape.** How do users relate to workspaces?
  - (a) **One user → one personal workspace** (simplest; matches "one PM's private
    decision loop" from product-design.md).
  - (b) **Users can belong to multiple workspaces**, with a switcher (team-shaped).
  - (c) Workspaces can have multiple members (sharing) — the fullest, most complex.
  My lean: **(a) one user, one workspace** for Phase 5 (the product is explicitly "one
  PM's private decision loop, not reporting"). Multi-member sharing is a later phase.
  Confirm — this hugely affects scope.

**Q4 — Migration of existing dogfood data.** The current single-tenant DB has real rows.
  - (a) **Auto-create a default "personal" workspace on first run and backfill all
    existing rows to it** (zero data loss; dogfood keeps working).
  - (b) Fresh start — new multi-tenant DB, old data abandoned.
  My lean: **(a)** backfill to a default workspace. Confirm.

**Q5 — Settings scope.** Today `settings` is global (LLM key, Brave key, news config,
  context budget). In multi-tenant these become **per-workspace** so each PM configures
  their own. BUT some (like the shared MVP LLM/Brave keys) might stay global/host-level.
  - (a) **All settings per-workspace** (each PM brings their own keys). Cleanest tenancy.
  - (b) **Per-workspace settings, with host-level env fallback** (if a workspace hasn't
    set a key, fall back to the host's env var — so the hosted deployment can provide a
    shared key while self-hosters set their own). Matches "hosted-first."
  My lean: **(b)** — per-workspace override, host env fallback. Confirm.

**Q6 — Auth surface / session.** Signed cookie session (itsdangerous / Starlette
  SessionMiddleware) with a `SECRET_KEY` from env? Login page at `/login`, logout at
  `/logout`, everything else requires a session. Confirm this shape.

**Q7 — Scope enforcement style.** How do repository calls get the workspace?
  - (a) **Explicit `workspace_id` param on every repository function** (loud, greppable,
    easy to test; more churn).
  - (b) A **scoped session/context object** carrying workspace_id, injected once per
    request.
  My lean: **(a)** explicit param — it makes cross-tenant leaks impossible to write by
  accident and is trivial to test. More edits, but safest. Confirm.

---

## Tasks (TDD; each ends with a commit) — DRAFT, pending answers

> Shapes assume the "my lean" answers. Sub-milestones so this doesn't land as one
> giant unreviewable change.

### Milestone A — Tenant data model + scoping (no auth yet)

**Task A1: Workspace + User models + default workspace.**
- `models.py`: `Workspace(id, name, created_at)`, `User(id, email, workspace_id,
  auth_provider, created_at)`. `repository` helpers; `get_or_create_default_workspace()`.
- Test: default workspace created idempotently; user attaches to a workspace.

**Task A2: Add `workspace_id` to all six tables + backfill.**
- Add nullable `workspace_id` FK to questions/sessions/session_messages/news_items/
  outcomes; make `settings` keyed by `(workspace_id, key)`.
- `init_db` backfills existing rows to the default workspace (Q4=a).
- Test: existing rows get the default workspace; new rows require one.

**Task A3: Thread `workspace_id` through repository + callers.**
- Every `repository.*` query filters by `workspace_id` (Q7=a: explicit param).
- Update all callers (pipeline, warroom, lenses, news, context_feed, api/*) to pass the
  current workspace.
- Test (THE invariant): create data in workspace A and B; assert every list/query in A
  never returns B's rows. Cross-tenant leak is impossible.

**Task A4: Per-workspace settings (Q5=b).**
- `settings.*` take `workspace_id`; `(workspace_id, key)` storage; resolver falls back to
  host env var when a workspace hasn't set a key (LLM/Brave keys).
- Test: workspace A's LLM model doesn't affect B; env fallback works when unset.

### Milestone B — Auth + request-scoped workspace

**Task B1: Pluggable AuthProvider (Q1=b).**
- `auth/` package: `AuthProvider` protocol; `LocalAuthProvider` (email-only, default);
  `GoogleAuthProvider` (Authlib OAuth2, active only when client id/secret configured).
- Test: local login creates/returns a user + workspace; provider selection by config.

**Task B2: Session + login/logout + auth gate.**
- Starlette `SessionMiddleware` (signed cookie, `SECRET_KEY` from env) (Q6).
- `/login` (renders provider-appropriate form/redirect), `/auth/callback` (Google),
  `/logout`. A dependency `current_user`/`current_workspace` that 302s to `/login` when
  unauthenticated; applied to all app routes.
- Test (TestClient): unauthenticated → redirect to /login; after local login →
  authenticated requests resolve the right workspace; logout clears session.

**Task B3: Wire request → workspace → repository.**
- Replace the ad-hoc `get_session` usage with `current_workspace` resolution; every
  route passes `workspace_id` into repository/pipeline calls.
- Test: two logged-in users see disjoint Inboxes/Outcomes/Settings.

### Milestone C — Hosted readiness (no infra stand-up)

**Task C1: `DATABASE_URL`-driven engine (Q2=a).**
- `db.py`: build the engine from `DATABASE_URL` env (default `sqlite:///…`), so Postgres
  is a config flip. Keep SQLite for tests. No Postgres stood up here.
- Test: engine URL respects `DATABASE_URL`; app boots on SQLite unchanged.

**Task C2: Config/secrets hygiene + deploy notes.**
- `SECRET_KEY`, `DATABASE_URL`, optional Google OAuth creds documented in README;
  never committed. `.env.example`. No real secrets in repo.

### Milestone D — Verification

**Task D1: End-to-end multi-tenant verification.**
- Two users log in (local provider), each configures their own news/product profile,
  each generates questions; assert full isolation across Inbox/Workspace/Outcomes/
  Settings. Google provider exercised only if creds are supplied (skip otherwise).
- Full `pytest -q` green (all Phase 0–4 tests updated for workspace scoping).
- Commit `test(phase5): end-to-end multi-tenant isolation`.

---

## Files likely to change (summary)

- Create: `auth/__init__.py`, `auth/base.py`, `auth/local.py`, `auth/google.py`,
  `api/auth.py` (login/logout/callback), `.env.example`, and ~6 test files.
- Modify (broad): `models.py` (Workspace/User + workspace_id on all tables + settings
  composite key), `repository.py` (workspace_id on every function), `settings.py`
  (per-workspace + env fallback), `db.py` (DATABASE_URL + middleware), `api/app.py`
  (SessionMiddleware + auth dependency on routers), and EVERY caller that hits the
  repository: `api/inbox.py`, `api/workspace.py`, `api/outcomes.py`, `api/news.py`,
  `api/settings.py`, `pipeline.py`, `warroom.py`, `lenses.py`, `news/relevance.py`,
  `context_feed.py`, `web/render.py` (login page + workspace name in the rail).

## Risks / tradeoffs

- **Blast radius.** This touches nearly every file. Mitigation: staged milestones (A: data
  scoping first, provably isolated, before auth; B: auth on top; C: hosting hooks). Keep
  each task's tests green before moving on. Do NOT combine milestones in one commit.
- **Cross-tenant leaks.** The whole point. Mitigation: explicit `workspace_id` params
  (Q7=a) + a dedicated isolation test that's run after every milestone.
- **Auth complexity vs testability.** Mitigation: pluggable provider with a `local`
  default (Q1=b) so the app stays runnable and tests stay offline; Google is additive.
- **Migration data loss.** Mitigation: backfill existing rows to a default workspace
  (Q4=a), tested.
- **Scope creep into sharing/teams.** Mitigation: one-user-one-workspace (Q3=a) for now.

## Verification checklist

- [ ] All tests pass with `PMQS_LLM_MODE=off`, on SQLite.
- [ ] Isolation invariant: workspace A never sees workspace B's data (every entity).
- [ ] Unauthenticated requests redirect to /login; local login works offline.
- [ ] Existing dogfood data backfilled to a default workspace (no loss).
- [ ] `DATABASE_URL` swap works (SQLite default; Postgres a config flip).
- [ ] No secrets (SECRET_KEY, OAuth creds, DB creds) committed.
- [ ] Policies never to GitHub; raw news never to GitHub; guard test green.
