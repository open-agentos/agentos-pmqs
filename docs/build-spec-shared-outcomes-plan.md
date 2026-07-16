# PMQs: Shared Outcomes — Implementation Plan

**Status:** Draft 3 — handoff spec
**Audience:** an AI coding agent picking this up cold, with no access to the conversation that produced it
**Repo:** `agentos-pmqs`
**Prerequisite:** PRs #58–#64 (Product switcher) merged to main

---

## 0. How to use this document

Sections 1–6 are the model. Section 7 is the schema. Section 8 is the migration order and it is not negotiable. Section 9 is the work, broken into reviewable units with acceptance criteria. Section 10 specifies behaviour. **Section 11 contains repo-specific traps that have already cost this project real time — read it before opening a PR.** Section 12 is out of scope. Section 13 needs a human.

**This document was written from a description of the schema, not from the code.** Before writing any migration, inspect the actual tables and column names and reconcile. Where this doc and the code disagree, the code wins — flag the discrepancy rather than forcing the doc's shape.

## 1. What PMQs is

A web interface for product managers, built on Open AgentOS (a GitHub-primitives agent orchestration system). It runs one PM's decision loop:

- **Inbox** — a short ranked list of questions needing a human decision, generated proactively in time-boxed daily batches by an 8-lens taxonomy (competitive positioning, growth/adoption, unit economics, risk & exposure, roadmap tradeoff, quality/reliability, org/execution drag, narrative/positioning).
- **Workspace** (a.k.a. war room) — a multi-pane surface for working a single question to a decision. Conversation on the left; Position document / Evidence / Impacts / Proposed questions on the right. Entered from the Inbox; the room's title *is* the question.
- **Outcomes** — a ledger of what got produced. Five types: **Issue, Policy, Document, Meeting, Question**. Only Issue is promoted to a real GitHub Issue; the rest are hosted-store records. **Policies must never be written to GitHub** — they are private to the customer.

Backend is Python/FastAPI, integrating AgentOS via its CLI. The hosted store is SQLite. `outcome` is a single table with a type discriminator plus a JSON payload.

## 2. Why this work exists

The value of PMQs compounds when several PMs work the same product inside it. The mechanism is **Slack-shaped, not Google-shaped**: it does not come from data volume across a global user base (that curve saturates), it comes from **primacy of the space**.

Where Slack's unit of value is a conversation, **PMQs' unit of value is the outcome** — the decision, policy, document, or meeting produced by facing up to a hard question. Outcomes are durable and citable, which makes this a *content* network effect rather than a *data* network effect.

> A member's outcomes become inputs to every other member's question generation, war-room framing, and position documents. The more the room has resolved, the more precise each subsequent decision becomes — because the system stops re-litigating settled ground and starts building on it.

The boundary is the **Product**. Nothing crosses it. This is not a commons, not cross-org, not federated. It is multiplayer within one product.

## 3. Domain model

Exactly **two levels**. There is no third.

| Slack | PMQs | Definition |
|---|---|---|
| Team / workspace | **Product** | The tenant-scoped unit. Repos, watchlist, lens weights. **Membership attaches here.** |
| `#channel` | **Workspace** (war room) | A room on one question. Always a subset of exactly one Product. Many per Product. **Shared by default.** |
| Private channel / DM | **Private Workspace** | Created private. Visible only to its owner. |

Two tenants tracking the same repo get two unrelated `product` rows pointing at the same URL. **Nothing is shared across tenants.**

**Naming collision, live in the code:** the UI calls the war room a "Workspace." The schema calls it a `session`. Separately, `workspace` in the schema (from #51) is a per-product container. Under this model that container has no conceptual home — there is no third level for it to occupy — so it folds into `product` and is deleted. See §8.

Throughout this document: **Workspace** = the room = today's `session` row.

## 4. Visibility rules

1. A Workspace is **shared** by default; it may be created **private**.
2. **Outcomes inherit their Workspace's visibility.**
3. A private Workspace's outcome may be **promoted** to the Product ledger.
4. Promotion is **one-way**: private → shared. Never shared → private.
5. The **Inbox is always private** to its member.
6. **Opening a Workspace publishes its question.** The inbox is private, but creating a room is a public act — as in Slack. This is the seam between the private and shared halves of the product.

There is no visibility settings page and no per-outcome privacy matrix. There are exactly two user actions: *create this room private*, and *promote this outcome*.

## 5. What is shared, what is not

| Object | Scope |
|---|---|
| Outcomes ledger | **Product** — shared across members |
| Policies | **Product** — always-on context for every member's agents |
| Position documents, Evidence | **Product** — attached to their Workspace |
| Workspaces (shared) | **Product** — visible to all members |
| Workspaces (private) | **Member** — owner only |
| Inbox items and their ranking | **Member** — always |
| Lens weights | **Product** |

## 6. The four loops

Sharing a ledger is just a shared folder. These loops are the network effect.

| # | Loop | Effect |
|---|---|---|
| 1 | **Policies as shared standing context** | A colleague's standing rule constrains my agents. Rides the existing unified context-feed (the same mechanism that feeds news, agendas, documents) — wider query, `retired_at IS NULL` filter. Smallest change, largest felt effect. |
| 2 | **Prior outcomes as lens input** | The lens pass sees what the Product has resolved. Questions build on settled ground instead of re-asking it. |
| 3 | **Cross-member dedup** | Widen the existing cross-lens dedup judgment to include Product outcomes and other members' open inbox items. Three verdicts: *suppress* (already decided), *reframe* (builds on outcome N), *route* (a colleague is already deciding this — surface their Workspace). |
| 4 | **Prior decisions as position-doc material** | The position document follows the California Voter Guide format (plain-language summary, consequence framing, neutral background, case for / case against). Prior decisions are the strongest available material. Cite with author and date. **A prior decision must be eligible for the *against* column.** |

## 7. Schema

### Target state

```sql
-- NEW
member (
  id               PRIMARY KEY,
  display_name     TEXT NOT NULL,
  external_subject TEXT NULL,          -- dormant; real identity attaches at Phase 5 auth
  created_at       TIMESTAMP NOT NULL
);

membership (
  member_id   REFERENCES member(id),
  product_id  REFERENCES product(id),
  role        TEXT NOT NULL DEFAULT 'member',   -- 'owner' | 'member'
  created_at  TIMESTAMP NOT NULL,
  PRIMARY KEY (member_id, product_id)
);

-- RENAMED, EVERYWHERE (schema, queries, routing, templates)
workspace_id  ->  product_id

-- DELETED
workspace                      -- folds into product; see §8 step 2

-- ALTERED
question + author_member_id    REFERENCES member(id)

session  + author_member_id    REFERENCES member(id)
         + visibility          TEXT NOT NULL DEFAULT 'shared'   -- 'shared' | 'private'

outcome  + author_member_id            REFERENCES member(id)
         + promoted_at                 TIMESTAMP NULL
         + retired_at                  TIMESTAMP NULL
         + superseded_by_outcome_id    NULL REFERENCES outcome(id)
```

### Design notes — do not "improve" these

- **`role` ships with no behaviour behind it.** One TEXT column now beats a migration later. Do not build an RBAC layer.
- **No `visibility` column on `outcome`.** Visibility has one source of truth — the Workspace — plus one exception, `promoted_at`. A denormalised copy on `outcome` can drift out of sync with its room. Resolve an outcome's visibility as: *shared if its session is shared, or if `promoted_at IS NOT NULL`*.
- **No `status` enum on `outcome`.** Active is `retired_at IS NULL`. Superseded is `retired_at IS NOT NULL AND superseded_by_outcome_id IS NOT NULL`. Retired-without-replacement is `retired_at IS NOT NULL AND superseded_by_outcome_id IS NULL`. No CHECK constraints to migrate later.
- **No `assignee_member_id`.** That is task management. Out of scope.

### Backfill

One `member` row for the existing single-tenant user. One `membership` row into every `product`, role `owner`. Every existing `question`, `session`, and `outcome` authored to that member. Same shape as the #52 migration — use it as the reference.

**None of this requires auth.** Phase 5 attaches real identities to `member.external_subject`. Everything here is buildable and testable single-tenant with stub members, which is why it is being done now: `author_member_id` costs nothing today and costs a multi-table backfill later.

## 8. Migration order

**Strictly sequential. Each step merges and goes green before the next starts.**

1. **`member` + `membership` + backfill.** Additive; nothing else depends on it yet.
2. **Fold `workspace` into `product`; rename `workspace_id` → `product_id` everywhere.** First inspect whether `workspace` carries any state `product` lacks — if so, migrate those columns onto `product` before dropping. Touches schema, queries, routing (#56's work), and templates.
3. **`session` gains `author_member_id` + `visibility`.**
4. **`outcome` gains `author_member_id`, `promoted_at`, `retired_at`, `superseded_by_outcome_id`.**
5. *(Optional, human decision — see §13)* **Rename `session` → `workspace`** so the schema matches the UI.

> ⚠️ **Steps 2 and 5 are two entities swapping names.** `workspace` → `product` and `session` → `workspace`. **Never do these in one PR.** Step 2 must be merged and green before step 5 is written. Doing both at once is how the data gets lost.

## 9. Work items

Each is one PR. See §11 for PR rules before opening any of them.

### Wave 1 — schema

| # | Title | Acceptance |
|---|---|---|
| 1 | `member` + `membership` tables, backfill | Tables exist; one member; one membership per product with role `owner`; existing rows authored to it; suite green |
| 2 | Fold `workspace` into `product`; `workspace_id` → `product_id` | No `workspace` table; no `workspace_id` identifier remains anywhere including templates; product switcher still works end-to-end; suite green |
| 3 | `session`: `author_member_id` + `visibility` | New sessions default `visibility='shared'`; a private session is retrievable only by its author; suite green |
| 4 | `outcome`: authorship, promotion, lifecycle | Columns exist and backfilled; `retired_at IS NULL` is the active predicate; suite green |

### Wave 2 — behaviour, ordered by when the effect is felt

| # | Title | Acceptance |
|---|---|---|
| 5 | Product-scoped ledger reads, authorship display, promote action | Ledger returns all members' outcomes for the product, filtered by §4's visibility resolution; each row shows its author; promote action flips `promoted_at` and is rejected on an already-shared outcome; **Inbox reads remain member-scoped** — assert this with a test |
| 6 | Policy context feed widened to Product — **Loop 1** | Any member's active Policy reaches every member's agents through the existing unified context-feed; retired policies do not; no new feed mechanism introduced |
| 7 | Workspace list view | See §10.1 |
| 8 | Prior-outcome retrieval for lens passes | See §10.2 |
| 9 | Prior-outcome awareness in question generation + dedup — **Loops 2, 3** | See §10.3 |
| 10 | Position doc: prior-decision citation — **Loop 4** | Retrieved prior decisions appear cited with author and date; a prior decision can appear in the *against* column; no new research pass added |

Items 5 and 6 together deliver the whole effect in usable form: a colleague's policies constrain your agents, and you can see who decided what. Everything after sharpens it.

## 10. Behaviour specs

### 10.1 Workspace list view (item 7)

The `Workspace` nav item currently opens the current room. It must open a **list**. Model it on the Google Docs list view.

| Column | Source |
|---|---|
| Name | the session title (= the question) |
| Owner | `author_member.display_name` |
| Last modified | `session.updated_at` |
| Outcomes | count of outcomes for that session |

- **Filter chips:** *Any owner* / *Owned by me* / *Not owned by me*. Backed by `session.author_member_id`.
- **Default sort:** last modified, descending.
- **Private Workspaces** appear only for their owner — like an unshared Doc, they are simply absent from everyone else's list.
- **Deliberately omitted:** Google Docs sorts by *last opened by me*, which requires a per-member view table (`session_view(member_id, session_id, last_opened_at)`). Not building it. The consequence — accepted — is that the default sort reflects team activity rather than personal activity, so the *Owned by me* filter does more work. Revisit only if the list becomes noisy in real use.
- Styling follows `docs/brand-design-system.md`. Hue carries **state, not identity** — do not colour rows by outcome type. Ledger-style tags stay neutral.

### 10.2 Prior-outcome retrieval (item 8)

```
select_prior_outcomes(product_id, lens, topic, token_budget) -> [Outcome]
```

- Filter: `retired_at IS NULL`, visible per §4.
- Rank by lens affinity × recency decay × type weight.
- **Cap by token budget, not row count.** The ledger grows monotonically; an unbounded feed is a cost and quality failure.
- **Policies bypass ranking** and are always injected (subject to the same budget) — that is what "standing rule" means.
- Do not dump the ledger into the prompt.

### 10.3 Prior-outcome awareness (item 9)

Widen the **existing** LLM dedup judgment — do not add a second one. Its evidence gains: Product outcomes (via 10.2) and other members' open inbox items.

Verdicts:
- **suppress** — already decided; do not raise.
- **reframe** — raise, but framed as building on outcome N.
- **route** — a colleague is already deciding this; surface their Workspace rather than raising a duplicate.

**Prior decisions are injected as positions to test, not as settled fact.** See §12's note on groupthink. The challenge/probe mechanic must be able to argue against a prior decision.

## 11. Repo conventions and traps

**These have already cost this project real time. They are not suggestions.**

- **Every PR must have `base=main` and a non-empty `closingIssuesReferences`.** Verify with the GraphQL `closingIssuesReferences` field before trusting it.
- **Never open a stacked PR (`base != main`).** GitHub only registers `Closes #N` against the default branch, so a stacked PR has empty `closingIssuesReferences`, Agent Intake classifies it `source:wild`, and it loops — intake comments on the PR, `issue_comment:created` is in intake's own trigger list, and `INTAKE_EXCLUDE_ACTORS` does not exclude `agentos-watcher[bot]`. One stacked PR produced 11 stub issues. Branches may chain locally; PRs must all target `main`.
- **Every PR needs an issue behind it.** A PR with nothing to close trips the same trap.
- **Repeat the keyword per issue.** `Closes #22, #23, #25` only registers #22. Write `Closes #22, Closes #23, Closes #25`.
- **`pmqs/pmqs/web/templates/app.html` is production code.** `render.py` splices data into it via regex anchored on its markup, and no test asserts on that markup — **it can break with CI green.** `TEMPLATE-CONTRACT.md` documents the anchors. The `workspace_id` rename (step 2) and the list view (item 7) both touch this surface.
- **Drift guards will fail you if you touch design tokens.** `tests/test_brand_doc.py` asserts every colour token in the template appears in brand doc §3 with a matching value and every font token in §4. `tests/test_logo.py` pins the mark's geometry. If you add a colour, document it in §3 in the same PR.
- **File issues unlabeled/inert.** Status labels auto-dispatch agents (`status:todo` → builder, `status:plan` → planner). Matt triages.
- Baseline was **200 passing tests** after PR #64. Do not regress it.

## 12. Out of scope

Do not build these. Each was considered and cut.

- **Cross-Product or cross-tenant sharing.** The Portfolio view is the only planned exception and it is not this work.
- **A federated/cross-org commons.** Different trust model, different legal surface.
- **Chat, comments, threads, presence, real-time.** The unit is the outcome, not the message. PMQs must not drift into competing with Slack.
- **Invitation flow.** Needs auth (Phase 5). Members are stub rows until then.
- **Workspace workflow states** (Draft → …). Parked deliberately.
- **Roles beyond `owner`/`member`.** No RBAC matrix.
- **Consequence tracking** (did the decision work?). The right long game; `retired_at`/`superseded_by` is the schema hook. Not now.
- **`session_view` / "last opened by me".** See §10.1.
- **PULSE metric changes.** Being handled separately.
- **Position-document rebuttals.** The case-for and case-against should each carry a rebuttal and currently don't. Known bug, tracked separately, not this work.

### Failure modes this design guards against

- **Landfill.** A shared ledger grows monotonically. Without lifecycle, the context pool fills with contradictory standing rules and the system gets *dumber* as the team gets busier. `retired_at` + `superseded_by_outcome_id` is the guard.
- **Context bloat.** §10.2's token budget.
- **Team groupthink.** Shared priors converge a team. If prior decisions reach the challenge mechanic as settled fact, PMQs becomes a consensus machine — the inverse of its purpose. Inject them as positions to test.
- **Attribution chilling.** If every decision is visible, PMs stop recording the messy ones. Private Workspaces are the escape hatch. **Count outcomes; never rank people.** No per-member metrics in the ledger summary strip, ever.

## 13. Decisions requiring a human

1. **§8 step 5 — rename `session` → `workspace`?** End state is `product` + `workspace`, matching the UI, which is cleaner forever. Cost is a second rename touching the template contract in a repo where markup breakage passes CI. Recommendation: do it, strictly after step 2 is merged and green, in its own PR. Matt's call.
2. **§8 step 2** — if `workspace` turns out to carry state that `product` lacks, stop and confirm the fold rather than guessing at where those columns belong.
