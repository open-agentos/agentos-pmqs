# Build Spec — Phase 5: Identity & Auth

**Status: PLAN ONLY. Not scheduled. Nothing here is implemented.**

Supersedes the previous version of this document, which described a codebase that
no longer exists. See §1 for the delta and why this doc is now roughly a third of
its former size.

## §0 How to use this document

1. **Code wins.** Written without repo access. Claims about current code are
   marked *(verify)*. Where code and doc disagree, code is right — amend the doc,
   don't force the code. This rule has already earned its keep twice on this
   repo.
2. **Prerequisite: `build-spec-deployment.md` ships first.** Not preference —
   §4.1.
3. Scale assumption: **~10 users, all invited personally.**
4. This document is kept current so it can be executed when the product question
   is settled. It is not a signal that the product question is settled.

---

## §1 What changed — this is no longer a tenancy project

The previous version opened with: six tables, no tenant column, settings global,
no identity. That was true when it was written. Since then:

- **#51/#52** — Product/Workspace schema, `workspace_id` scoping, backfill.
- **Wave 1 (#66/#69/#71)** — workspace folded into product; `Member` and
  `Membership` introduced; `session.author_member_id` and `session.visibility`.
- **Wave 2 (#80/#81, + #85–#87 pending)** — `list_ledger_outcomes` as the single
  implementation of the §4 visibility rule; policy context feed scoped by a
  **required** `product_id`.

So the tenant boundary already exists, and the previous doc's Milestone A —
"introduce the Workspace as the tenant boundary" — is substantially built under
different names.

> **Phase 5 is an identity project, not a tenancy project.** Tenancy landed with
> the Product switcher and Shared Outcomes. What is missing is: *who is the
> current member*, proven by a real login — plus the access-control decision about
> who is permitted to become one.

### §1.1 Disposition of the previous doc's open questions

| | Was | Now |
|---|---|---|
| Q1 auth provider | (b) pluggable, local default | **(c) Google only.** Protocol dropped — §6.2 |
| Q2 SQLite/Postgres | (a) defer | **Moved** → deployment §12 Q1 |
| Q3 tenant model | (a) one-user-one-workspace, no sharing | **Void.** Decided and shipped as Product + Membership — the opposite answer |
| Q4 backfill | (a) backfill | **Done** (#52, Wave 1). What remains is one row — §6.5 |
| Q5 settings scope | (b) per-workspace + env fallback | **Re-asked** in the Product/Member world — §6.6 |
| Q6 session cookie | signed cookie + `SECRET_KEY` | Kept. `SECRET_KEY` provisioning → deployment §4 |
| Q7 scope enforcement | (a) explicit param | **Answered and upgraded** — §3.1 |

The previous doc's risk register entry "scope creep into sharing/teams —
mitigation: one-user-one-workspace" is a dead letter. The scope crept, deliberately,
and shipped.

---

## §2 Naming — resolve this before writing any code

"Workspace" currently carries three meanings. The doc must stop doing this.

| Term | Means | Status |
|---|---|---|
| **Product** | The membership boundary. Global row; a person reaches it via `Membership`. | Canonical |
| **Workspace** | A room / war room. **Is a `session` row.** The UI name for a session. | Canonical, but note the collision below |
| ~~`workspace` (schema)~~ | The old per-product container from #51/#52 | **Folded into `product`** by PR #69. Gone. |
| ~~"Workspace" (tenant)~~ | This doc's former usage | **Retired.** The tenant concept is Product + Membership |

**Live collision to be aware of:** the UI calls a `session` a "Workspace". The
#51/#52 schema also had a `workspace`. The second is gone, but old code comments,
issue text and this repo's docs may still use it either way. When reading, assume
nothing.

This doc uses **Product** and **room** (for `session`) throughout.

---

## §3 The invariant

Two levels, not one:

> A member can read only:
> 1. rows belonging to Products they hold a `Membership` in, **and**
> 2. within those, only rooms visible to them per the §4 visibility rule of
>    `build-spec-shared-outcomes-plan.md` — outcomes inherit their room's
>    visibility; a private-room outcome is invisible until promoted.

Level 2 is already implemented, once, in `list_ledger_outcomes`, and reused by
retrieval and position-doc citation so that neither becomes a side channel around
it *(verify)*.

**Therefore Phase 5's testable job is narrow:**

- prove `current_member_id()` returns the right member, from a real login;
- prove no read path goes *around* `list_ledger_outcomes`;
- prove no route is reachable without a guard.

### §3.1 Scope enforcement style — settled by precedent

The previous Q7 leaned "explicit parameter". That is right but insufficient.
Wave 2 item 6 proved why: the policy context feed took no product argument at
all, so every Product's policies reached every Product's agents — a live
cross-product leak, contradicting the hard requirement that product data streams
must not cross. The fix made `product_id` a **required** kwarg so it cannot
return by omission.

**Rule for all Phase 5 work: scope parameters are explicit AND required.** A
scope argument with a default is a leak with a delay.

---

## §4 Prerequisites

### §4.1 Deployment (hard block)

Google OAuth requires a stable public HTTPS redirect URI. That requires a domain.
That requires the deployment. Phase 5 cannot start until deployment §11 D3 is
done. See `build-spec-deployment.md`.

### §4.2 CI running pytest — #79 (hard block)

Phase 5's deliverable is an invariant. The invariant is enforced by tests. No
workflow runs the tests. Until #79 is fixed, the isolation suite in §7.3 is a
document, not a guarantee — it protects nothing the first time someone pushes
without running pytest locally. Deployment §11 D1.

### §4.3 #78 — the news relevance pass is product-blind (in-scope block)

`pmqs/news/relevance.py` batches every product's unprocessed news into one
prompt, scores against one global `product_profile`, and creates Questions with
**no `product_id`**. Harmless today only because Phase 4 isn't live. The moment
it is, in a multi-tenant world, it is Wave 2 item 6 again with strangers' data.

This is the same root cause as the documented `NewsItem.url` uniqueness gap.

**Either fix #78 within Phase 5, or make the news cron refuse to start when more
than one Product has members.** Do not ship auth over a known leak on the grounds
that the leaking feature is off — the feature being off is a scheduling accident,
not a control.

---

## §5 Scope

**In:**
- Google identity bound to `Member`; invite-only allowlist; bootstrap of the
  existing default member
- Google OAuth login, session cookie, route guard
- Replacement of the `current_member_id()` seam
- Settings re-scoped to Product; host-provided API keys; per-Product cost guard
- Isolation + route-guard test suites

**Out:**
- Pluggable auth / any provider abstraction → **Phase 6** (self-host packaging).
  It is only self-hosters who need it.
- Any non-Google IdP, SSO, SAML, org directories
- Open sign-up, billing, subscriptions
- BYO API keys (option B) — **designed here (§6.6), built at 5–10 users**
- Password reset, email verification, account deletion UX, GDPR export
- Roles/permissions within a Product. Membership is binary. Do not add a role
  column "for later" — the standing directive is to reduce complexity, and an
  unused role column is complexity that will acquire a meaning by accident.

---

## §6 Design

### §6.1 Identity model

**Blocking question, needs a code check — see §9 Q1.** Everything below assumes
`Member` represents *a person* and `Membership` is the `(member, product)` join.
If `Member` is per-Product, a separate `User` table is required and §6.1/§6.5
change shape.

Assuming the former, `Member` gains:

| Column | Notes |
|---|---|
| `google_sub` | Google's stable subject ID. **Unique, nullable until bound.** |
| `email` | Last-known address. Display only — never an identity key after binding |
| `email_verified_at` | |
| `last_login_at` | |

**`sub`, not email, is the identity.** Email addresses get reassigned, aliased,
and changed; `sub` is permanent per Google account. Match the *invite* on email
(that's all you know before they log in), then bind `sub` on first login and
match on `sub` forever after.

New table `invite`:

| Column | Notes |
|---|---|
| `email` | The address invited |
| `product_id` | Which Product they're being invited to |
| `invited_by_member_id` | |
| `created_at`, `accepted_at`, `revoked_at` | |

**Membership is the allowlist.** There is no separate allowlist table and no
`is_allowed` flag. An accepted invite produces a `Membership` row; that row is
the permission.

### §6.2 Google OAuth — one provider, no abstraction

Authlib. `/login` → Google → `/auth/google/callback`.

- Verify the ID token. **Check `email_verified`** — an unverified claim is not an
  identity.
- Read `sub`, `email`, `email_verified`. **Discard everything else.**
- **Store no Google tokens.** Not the access token, not a refresh token. We never
  call a Google API after login. This is consistent with the standing product
  decision that Google Docs/Calendar must not be a dependency for anything except
  login — and it deletes an entire class of secret-storage, expiry and revocation
  problems. If a future feature wants Calendar, it asks for its own consent then.
- **No `AuthProvider` protocol.** One provider means one code path. The previous
  doc's option (b) would have shipped a passwordless local login route into
  production as the default — a footgun purchased in exchange for an abstraction
  serving a Phase 6 audience that doesn't exist yet.

Tests stay offline via §7.1, not via a shipped local provider.

### §6.3 Session

Starlette `SessionMiddleware`, signed with `SECRET_KEY` (deployment §4).

- Cookie carries `member_id` and nothing else. It is **signed, not encrypted** —
  assume the user can read it. Nothing secret goes in.
- `https_only=True`, `httponly=True`, `samesite="lax"`.
- Lifetime: see §9 Q4.
- **Re-check membership on every request**, from the DB, not from the cookie. A
  revoked membership must take effect on the next request, not on the next login.

### §6.4 The seam

`members.current_member_id()` is **the** Phase 5 auth seam — deliberately built
as one function so this phase is a replacement, not a scavenger hunt *(verify it
is still the only caller-facing entry point)*.

Today it returns the default member. After Phase 5 it reads the session, loads
the member, and raises a 401/302 when absent. **If there is a second way to learn
who the current member is, this phase's job includes deleting it.**

FastAPI dependency wrapping it; every route depends on it; §7.4 asserts that
mechanically.

### §6.5 Invite-only, and the bootstrap

**First login:**

1. Google returns `sub` + verified `email`.
2. Known `sub` → load member, update `last_login_at`, done.
3. Unknown `sub`, email matches an open `invite` → bind `sub` to the invited
   member, create `Membership`, mark invite accepted.
4. Unknown `sub`, no invite → **a plain "you'll need an invite" page**, not a 403.
   Log the attempted address so you know who tried.

There is no path that creates a Product for a stranger. Open sign-up is a GA
concern.

**Bootstrap:** `BOOTSTRAP_ADMIN_EMAIL` (deployment §4). On first login of that
address, bind it to the **existing default member** rather than creating a new
one — so the dogfood data from Phases 0–4 survives the transition intact and
attached to a real identity. This is the entirety of what remains of the old Q4:
one row, not a backfill. The backfills already ran under #52 and Wave 1.

Invites are created by a member of a Product, for their Product. UI surface: see
§9 Q3.

### §6.6 Settings scope and API keys

**Settings re-scope.** Settings is currently a global key/value store *(verify)*.
In the Product/Member world:

- **Product-scoped:** product profile, news watchlist (industry, keywords,
  companies, product names, sources), lens weights. These are shared between a
  Product's members — which is the whole point of membership. `(product_id, key)`.
- **Host-scoped (env):** API keys, model selection, cost ceilings. See below.
- **Member-scoped: none.** Deliberately zero. Add the first one when there is a
  concrete need, not in anticipation of one.

**API keys — decided: option A now, option B at 5–10 users.**

*Option A (this phase):* host-provided keys from env. Users never see a key
field. Nothing secret in the database. The early token spend is customer
acquisition cost — users who haven't seen the product work will not hand over a
key, so charging them for the privilege of evaluating it is a dead end.

*Option B (designed here, built at the trigger):* BYO keys, **Product-scoped**,
encrypted at rest with `SETTINGS_ENCRYPTION_KEY`, write-only in the UI (never
rendered back — show `sk-…4f2a`), falling back to host env when unset.

Product-scoped, not member-scoped, and this is not arbitrary: **question
generation is a nightly Product-level batch. Whose key runs it for a
three-member Product?** A member-scoped key has no answer to that. A
Product-scoped key does.

To make B a column plus a resolver rather than a redesign, Phase 5 builds the
resolver now with a single branch:

```
resolve_key(product_id) -> str:
    # Phase 5: host env only.
    # Option B adds one branch above this line. Nothing else changes.
    return env[...]
```

Every call site goes through it from day one.

*Rejected: keys in `localStorage`.* Three reasons, the third fatal: (1) the LLM
calls are server-side, so the browser must transmit the key on every request and
it lands in our process anyway — a step added, not an exposure removed; (2)
`localStorage` is readable by any XSS on the page and is not safer than an
encrypted column whose key lives in env; (3) **the core loop is a nightly batch
that runs with no browser open.** A key that exists only in a tab cannot be used
by the 6am job. It would leave a product that generates questions only while
someone watches it — the inverse of the design.

### §6.7 Cost guard

Option A means the host pays for other people's tokens. Without a ceiling, "I
can't afford that" is a hope.

- Per-Product **monthly token/spend budget**, defaulting from env.
- Checked **before** generation, not after — a post-hoc check is a report.
- On exceed: generation halts, the Product is flagged, the owner sees it. Nothing
  crashes.
- Cost data already flows through the session indicator (exchanges / cost /
  duration / outcomes) — reuse that, don't invent a second accounting.
- Interactive use and the nightly batch draw on the same budget.

This is also the mechanism that tells you when to build option B: the first
Product to hit its ceiling is the trigger, and it will arrive before the
5–10 user count does.

---

## §7 Test strategy

### §7.1 Offline

No test may talk to Google.

- **Most tests:** FastAPI dependency override on the `current_member` dependency.
  Fast, no HTTP, no cookie.
- **A small set:** exercise the real callback with a mocked token endpoint and a
  synthetic ID token, because the dependency override bypasses the very gate this
  phase exists to install. Cover: unverified email rejected; unknown `sub` with
  no invite rejected; unknown `sub` with invite binds; known `sub` logs in;
  revoked membership rejected on next request.

### §7.2 Fail closed

Shared Outcomes' dedup deliberately fails **open** (no LLM → `raise`), because
suppressing a novel question is invisible and unrecoverable while raising a
duplicate costs a minute.

**Auth inverts that. Every ambiguity fails closed.** No member → no data. No
membership → no data. Broken cookie → login page. There is no degraded mode.

### §7.3 The isolation suite

Parametrised over **every** read path: member A, member of Product 1 only, sees
zero rows from Product 2 — questions, outcomes, sessions, messages, news,
settings. And within Product 1: A does not see B's private room, and does see B's
promoted outcome.

### §7.4 Guard tests (the ones that survive contact)

Point tests decay. These don't:

- **Route guard test:** enumerate the app's routes and assert every non-public one
  depends on the auth dependency. A new unguarded route then fails CI on the PR
  that adds it, rather than in production six weeks later. Explicit allowlist for
  `/login`, `/auth/google/callback`, `/healthz`, `/favicon.svg`.
- **Side-channel test:** assert no module outside the visibility module issues a
  direct query against the outcome table — i.e. that `list_ledger_outcomes`
  remains the single implementation of §3 level 2. AST-based *(see §9 Q5 — may be
  more trouble than it's worth)*.

This repo already runs drift guards of exactly this shape (`test_brand_doc.py`,
`test_logo.py`), so the pattern is established.

---

## §8 Milestones

| | | Done when |
|---|---|---|
| **P5.0** | Prereqs | Deployment D1–D3 green; #78 resolved or the news cron refuses multi-Product start |
| **P5.1** | Identity schema | `Member` identity columns + `invite` table + migration. No login yet; seam still returns default. Suite green |
| **P5.2** | Login | Google OAuth, session, guard, invite flow, bootstrap binding. Seam reads the cookie. §7.1 tests pass |
| **P5.3** | Settings + keys | Settings Product-scoped; `resolve_key` in place at every call site; cost guard enforcing |
| **P5.4** | Guards | §7.3 isolation suite + §7.4 route-guard test green in CI |
| **P5.5** | Cutover | Deployed; you log in as yourself against your own historical data; one invited friend logs in and sees nothing of yours |

**P5.5's acceptance test is the whole phase in one sentence:** an invited friend
logs in and sees nothing of yours.

---

## §9 Open questions

**Q1 — Is `Member` a person or a person-within-a-Product?** *(blocking; code
check)* Everything in §6.1 assumes `Member` = person and `Membership` =
`(member, product)`. If `Member` is per-Product, then a person who joins two
Products has two Member rows, identity cannot hang off `Member`, and a `User`
table is required with `Member` becoming the join. **Check before writing
anything.** *(Lean, if it's per-Product: add `User`, hang `google_sub` there,
leave `Member` alone — do not refactor `Member` under Shared Outcomes' feet.)*

**Q2 — Invited email ≠ Google email.** Someone invited at `matt@work.com` logs in
with `matt@gmail.com`. Lean: **reject and name the expected address**. Anything
cleverer is an account-takeover vector.

**Q3 — Where do invites get created?** Lean: Settings, Product-scoped, minimal —
an email field and a list of pending invites. Not a members-management screen.
Related: does the inviter need to already be a member of that Product (lean:
yes, binary membership, no roles per §5).

**Q4 — Session lifetime.** Lean: 30 days rolling, no refresh flow (we hold no
Google tokens, so there is nothing to refresh — re-login is the whole story).

**Q5 — Is the §7.4 side-channel test worth building?** It's the highest-value
guard and the most brittle. Lean: build the route-guard test (cheap, mechanical);
try the side-channel test and **delete it if it fights you** — a guard that cries
wolf gets disabled, which is worse than not having it.

**Q6 — Multi-Product landing.** A member of two Products lands where? Lean: most
recently active; the Product switcher (#55) handles the rest. Minor.

**Q7 — Does the retired global settings table hold rows worth migrating?**
*(code check)* Probably your own dogfood config. Migrate to the default Product
in the P5.1 migration.

---

## §10 Risks

| Risk | Mitigation |
|---|---|
| **#79 unresolved when this ships.** The isolation suite exists but nothing runs it. The invariant is decorative. | Hard prerequisite. Not negotiable — it is the difference between this phase working and appearing to work |
| **Q1 is wrong.** `Member` turns out to be per-Product; §6.1 and §6.5 are rebuilt mid-phase | Check first. It's a five-minute read of the Wave 1 migration |
| **This doc goes stale again.** It happened once already, over one workstream | It will happen again if Shared Outcomes Wave 3+ lands before this executes. Re-run §1 against the repo before P5.1, not after |
| **Draft-1 syndrome.** The Brand doc was written against an imagined component inventory rather than the built product, and §7's "settled" claim didn't hold. This doc is written without repo access | Every *(verify)* is an instance. §0 rule 1 is the mitigation, and it only works if it's actually applied |
| Option A cost overrun | §6.7 budget guard, enforced before generation |
| Cookie secret leak | `SECRET_KEY` in env only, rotatable (rotation logs everyone out — acceptable at ten users) |

---

## §11 Explicitly deferred to Phase 6

Pluggable auth, any provider abstraction, self-host packaging, BYO-everything.
Phase 6 is deliberately last and nothing in Phase 5 should pay a complexity tax
on its behalf.
