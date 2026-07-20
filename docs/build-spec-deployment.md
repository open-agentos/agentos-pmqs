# Build Spec — Deployment

**Status: PLAN ONLY. Not scheduled. Nothing here is implemented.**

## §0 How to use this document

1. **Code wins.** This doc was written without repo access. Every claim about the
   current codebase is marked *(verify)* where it matters. If code and doc
   disagree, code is right and the doc gets amended — do not force code to match
   the plan.
2. This doc is a **prerequisite for `build-spec-phase-5.md`**, not a companion to
   it. See §1 for why the ordering is structural rather than preference.
3. Scale assumption throughout: **~10 users, all invited personally.** Every
   decision below is made at that scale. Re-open this doc at 50.
4. Budget ceiling: **~$5–10/month.** This is a real constraint, not a target.

---

## §1 Why this precedes Phase 5

Three hard dependencies, in order of hardness:

1. **Google OAuth needs a stable public HTTPS redirect URI.** You cannot register
   the OAuth client properly until the app has a domain. Phase 5 is blocked on
   this, full stop.
2. **The database stops being erasable.** Today the DB is a file you delete when
   the schema changes. The moment other people's decisions live in it, schema
   change requires migrations (§5). That is a habit to establish *before* there
   is data to lose, not after.
3. **Tests must gate deploy.** Issue #79: no CI workflow runs pytest. Phase 5's
   entire value is a cross-tenant isolation invariant. An invariant enforced only
   by tests that nothing runs is decoration. See §10.

### §1.1 Pre-deployment product-boundary gate

Before putting this instance in front of another person, verify the current
multi-product boundary locally. The Product switcher, `/api/workspaces`, and
every `/w/{product-slug}/...` route must be membership-scoped. A product slug is
not an authorization token: a member who is not attached to that Product gets a
404, and must not learn whether the Product exists.

This is now enforced in the pre-auth code path:

- product listings and the switcher are filtered through the acting Member's
  Membership rows;
- scoped Inbox, Workspace, Outcomes, and Product Settings routes reject an
  unauthorized Product slug;
- Workspace session routes verify both the session's Product and the requested
  Product slug;
- the legacy unprefixed mount remains only as a compatibility path for the
  single-account dogfood database; product-scoped navigation uses `/w/{slug}`;
- Workspace action redirects and injected navigation preserve the active Product
  instead of falling back to the oldest/default Product.

The regression suite covers these walls, but the first-user smoke test in §11
must still exercise them through a browser. Do not interpret a clean page load
of `/` as proof of isolation.

---

## §2 Target

| | |
|---|---|
| Host | Hetzner Cloud **CAX11** — 2 vCPU (Ampere ARM), 4 GB RAM, 40 GB SSD, 20 TB traffic |
| Cost | ~€5–6.50/mo all-in incl. IPv4. **Prices moved in the June 2026 adjustment — confirm current rate in console before committing.** |
| Region | Germany or Finland (CAX is EU-only) |
| Orchestration | Docker Compose. **No PaaS.** |
| TLS / routing | Caddy (automatic Let's Encrypt) |
| Database | PostgreSQL, containerised, volume-persisted (but see §12 Q1) |
| Scheduling | cron service in the compose file |
| Deploy | GitHub Action → SSH → `docker compose up -d --build` |

### §2.1 Why no PaaS

Coolify was the initial candidate and was dropped on arithmetic. Its control
plane alone wants 2–4 GB RAM, which pushes the box to a CAX21 at ~€8.50/mo — the
top of budget, most of it spent running a dashboard for a single application. It
also brings its own maintenance surface (frequent updates, occasionally needing
manual intervention) and its own hardening requirements.

At fifteen services Coolify is a good deal. At one app and ten friends it is a
second system to operate. What it would have given us costs ~20 lines to replace:

| Coolify feature | Replacement | Section |
|---|---|---|
| Backups to S3 | `pg_dump` cron → object storage | §6 |
| Deploy on push | GitHub Action over SSH | §8 |
| Scheduled tasks | cron service in compose | §7 |
| Secrets UI | `.env` on the box, `chmod 600` | §4 |
| Dashboard | `docker compose logs` | — |

ARM is not a compromise here: on Hetzner's own hardware, Postgres benchmarks
~6% more TPS and HTTP ~15% more concurrent connections on CAX11 vs the x86 CX22,
at ~17% less cost. Python, Postgres and Caddy all publish ARM64 images.

**Revisit trigger:** more than two deployed services, or a second environment.

---

## §3 Topology

Single box, four compose services on a private bridge network:

```
caddy    :80 :443   → public. Terminates TLS, proxies to web.
web      :8000      → internal only. FastAPI/uvicorn. 1 worker (see §12 Q1).
db       :5432      → internal only. NEVER published to the host.
cron                → no ports. Runs the scheduled jobs in §7.
```

`web` and `cron` build from the same image and differ only in command. This
matters: the batch jobs must run the same code as the app, with the same
migrations applied.

**Volumes:** `db_data` (Postgres), `caddy_data` (certificates — losing this means
re-issuing certs and hitting Let's Encrypt rate limits).

---

## §4 Secrets and configuration

`.env` on the box at `/srv/pmqs/.env`, `chmod 600`, **never in git**. Injected via
compose `env_file`. A copy lives in a password manager; losing the box without
that copy means losing `SETTINGS_ENCRYPTION_KEY` and therefore any encrypted
column, permanently.

Expected variables (Phase 5 marks which are consumed by the auth work):

| Var | Purpose | Phase |
|---|---|---|
| `DATABASE_URL` | Postgres DSN | deploy |
| `SECRET_KEY` | Session cookie signing | 5 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth client | 5 |
| `PUBLIC_BASE_URL` | Redirect URI construction | 5 |
| `BOOTSTRAP_ADMIN_EMAIL` | Binds the existing default member on first login | 5 |
| `ANTHROPIC_API_KEY` | Host-provided LLM key (option A) | 5 |
| `BRAVE_API_KEY` | News fetch (Phase 4, not live) | 4 |
| `SETTINGS_ENCRYPTION_KEY` | Reserved — encrypts BYO keys (option B) | 5+ |
| `BACKUP_S3_*` | Backup destination | deploy |

**Rule:** no secret is ever read from the database. Host keys come from env.
Per-Product BYO keys (option B, later) are the only secrets that will live in the
DB, and they are encrypted with `SETTINGS_ENCRYPTION_KEY` — which itself stays in
env. See `build-spec-phase-5.md` §6.6.

---

## §5 Migrations — Alembic

**Current state *(verify)*:** table creation and data backfills both happen inside
`init_db` at startup. This is correct for an erasable SQLite file and wrong for a
hosted database with other people's data in it.

Adopt Alembic:

- **One baseline migration** capturing today's schema as-is. Do not take the
  opportunity to tidy anything; a baseline that doesn't match production exactly
  is worse than an ugly one.
- Every subsequent schema change is a numbered script. Alembic tracks what has run
  against a given database.
- **Data backfills move out of `init_db` and into migrations.** The Product
  switcher and Wave 1 backfills already ran against the local DB; they must not
  re-run in production. The baseline captures the post-backfill state, so this is
  mostly a deletion job.
- Deploy runs `alembic upgrade head` **before** the new `web` container takes
  traffic (§8). Never by hand.

**The trap to avoid:** authoring migrations against SQLite and running them
against Postgres. SQLite has no real `ALTER TABLE`, so Alembic emulates it by
rebuilding the table (batch mode); the resulting scripts and the type coercions
around them do not always mean the same thing on Postgres. Pick one engine and run
it *everywhere* — dev, tests, production. See §12 Q1.

**Autogenerate is a draft, not an answer.** Every generated migration gets read
before it's committed.

---

## §6 Backups

The backup is what makes a bad migration survivable rather than terminal. It is
not optional and it is not "later".

- `pg_dump` on a daily cron → S3-compatible object storage. Cloudflare R2's free
  tier (10 GB-month) is more than this will ever need; Hetzner Storage Box is the
  alternative.
- Retain 30 dailies. Compressed dumps of this database will be measured in
  megabytes.
- **A backup you have not restored is a rumour.** One documented restore drill
  before the first real user logs in, and the runbook goes in this repo.
- Additionally: snapshot the box before any deploy that carries a migration.

---

## §7 Scheduled jobs

The `cron` service. This is why the browser-side key idea failed and why the
scheduler is a deployment concern rather than an afterthought — **the product's
core loop runs when nobody is watching**.

| Job | Cadence | Status |
|---|---|---|
| Daily question batch (time-boxed regeneration) | daily, early | live |
| News fetch + relevance pass | daily | **Phase 4 — not live.** Blocked on #78, see phase-5 §4 |
| `pg_dump` → object storage | daily | this doc §6 |

Jobs are single-instance and must be idempotent — a retried batch must not
double-generate a day's questions. *(verify how the current batch guards this)*

---

## §8 Deploy

GitHub Action on push to `main`:

1. Run the test suite (§10). **Fail = stop.**
2. SSH to the box.
3. `git pull`
4. `docker compose build`
5. `docker compose run --rm web alembic upgrade head`
6. `docker compose up -d`

Steps 5 and 6 are ordered deliberately: migrate, then swap. There is no
zero-downtime story here and there does not need to be one — ten friends will not
notice a fifteen-second gap, and pretending otherwise buys blue/green complexity
for nothing.

Rollback: `git checkout <prev>` and repeat. **Note that this does not roll back a
migration** — schema rollback is the backup (§6), not a `downgrade` script. Write
migrations that are safe to leave in place if the app rolls back (add columns
before using them; drop them a release later, never in the same one).

---

## §9 Hardening

The default install of anything Docker-shaped is not hardened. Specifically:

- **Firewall at the Hetzner Cloud level, not `ufw`.** Docker's interaction with
  iptables can bypass local UFW rules — `ufw status` will report you're protected
  while a published port sits open to the internet. This is the single most
  common way a hobby box gets popped. Allow 22, 80, 443 at the project firewall
  and nothing else.
- Never publish `5432`. `db` is reachable on the compose network only.
- SSH: key auth only, password login disabled, root login disabled.
- Unattended security upgrades on.
- Caddy handles HSTS and cert renewal; don't hand-roll TLS config.

---

## §10 CI — resolving #79

Prerequisite, not a nice-to-have. Today the only workflows are the AgentOS agent
workflows (intake / orchestrator / settlement); every "suite green" acceptance
criterion in every build spec, and §11's "do not regress the baseline", is
verified locally and enforced by nothing.

Minimum: a workflow running `pytest` on push and PR, with a Postgres service
container (§12 Q1), which the deploy job depends on.

Baseline at time of writing *(verify)*: 236 on main, 317 with the four open Shared
Outcomes PRs merged.

---

## §11 Milestones

| | | Done when |
|---|---|---|
| **D1** | CI runs pytest (#79) | Suite runs on push + PR; red PR is visibly red |
| **D2** | Alembic baseline | `alembic upgrade head` on an empty DB produces today's schema; backfills removed from `init_db`; CI runs against the same engine as prod |
| **D3** | Box + Compose + Caddy | Box provisioned, firewall at project level, `https://<domain>` serves the app over a valid cert |
| **D4** | Backups + restore drill | Dump lands in object storage on schedule; a restore has been performed and documented |
| **D5** | Deploy pipeline | Push to `main` → tests → migrate → swap, with no human on the box |
| **D6** | Scheduled jobs | Daily batch runs on the box, idempotent, with logs you can find |

**D1–D2 are the ones that matter.** D3–D6 are an afternoon. D1 and D2 are the
ones that stop this from becoming unrecoverable later.

### §11.1 First-user release checklist

Run this in order immediately before inviting anyone:

1. Confirm the local dogfood database has the intended default Product and that
   every existing Product has the expected Membership for the bootstrap Member.
2. Log in/use the app as the bootstrap user and switch between two Products.
3. From each Product, click Inbox, Workspaces, and Outcomes; confirm the URL
   retains `/w/{slug}` and the content remains that Product's content.
4. Open a direct `/w/{other-slug}/...` URL while acting as a member of only one
   Product; expect 404 and no product data in the response.
5. Run the full test suite and inspect the CI result, not just the local result.
6. Take the pre-deploy database backup/snapshot and record where the restore
   artifact is stored.
7. Only then proceed to Google OAuth and invite the first external user.

If any of steps 2–4 fail, stop deployment. Do not paper over the issue by
deleting the local database: that can hide a routing or authorization defect.

---

## §12 Open questions

**Q1 — Postgres, or stay on SQLite?** *(needs a decision before D2)*

At ten users SQLite genuinely works: WAL mode, one writer, short transactions,
and the backup becomes a file copy. It is the "dead simple" answer and the
original Phase 5 spec's lean was to defer.

The argument against is not throughput, it's §5's trap: the `cron` service is a
second writer, and more importantly **tests, dev and prod should run the same
engine or migrations become a dual-target problem forever**. If tests run SQLite
and prod runs Postgres, every migration is written against a database that lacks
`ALTER TABLE` and deployed to one that has it. That divergence is the expensive
thing — not the 200 MB of RAM.

- **(a) Postgres everywhere, including tests.** *(lean)* Costs one compose
  service, ~200 MB RAM, and 6 lines of GitHub Actions service container. Buys one
  engine, one migration target, no surprises at cutover.
- (b) SQLite everywhere. Cheapest, simplest, and defers the Postgres migration to
  a moment when there *is* data to migrate — i.e. the expensive moment.
- (c) SQLite in tests, Postgres in prod. **Do not do this.** Named only so it's
  visibly rejected.

**Q2 — Object storage for backups: Cloudflare R2 or Hetzner Storage Box?** Lean
R2 (free tier covers it, off-provider so a Hetzner incident doesn't take the
backups with the box). Storage Box is one less account.

**Q3 — Domain?** Needed before Phase 5 can register the OAuth client. No lean —
your call.

**Q4 — Does anything need a staging environment?** Lean **no** at this scale; the
box is €5 and a second one doubles that for an app with ten users. Revisit when a
migration first scares you.

**Q5 — Uvicorn worker count.** Lean 1 on a 2-vCPU box, particularly if Q1 lands
on SQLite (where >1 writer process invites lock contention). Revisit if the daily
batch and interactive use start colliding.

---

## §13 Out of scope

- Zero-downtime deploys, blue/green, load balancing
- Multi-region, replicas, connection pooling beyond SQLAlchemy defaults
- Observability beyond container logs (revisit when there's something to observe)
- Self-hosted OSS packaging — that's Phase 6, and it is deliberately last
- Anything that assumes more than ~10 users
