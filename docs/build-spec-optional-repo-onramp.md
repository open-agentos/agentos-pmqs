# PMQs: Optional-Repo On-ramp — Implementation Plan

**Status:** Draft 1 — handoff spec
**Audience:** an AI coding agent (or Matt) picking this up cold, with no access to the conversation that produced it
**Repo:** `agentos-pmqs`
**Prerequisite:** the onboarding-research wave is merged (`docs/build-spec-product-onboarding.md`; `api/products.py::add_product`, `api/products.py::research_product_endpoint`, `web/render.py::_product_settings_sections`, `api/product_form.py::apply_product_config` all on `main`).

---

## 0. How to use this document

§1–§3 are the *why* and the *shape*. §4 is the data-model change — the one real piece of surgery. §5 is a latent bug this refactor has to fix or it silently does the wrong thing. §6–§8 are the code changes, grounded in the current files. §9 names the Phase-2 seam and explicitly parks it. §10 is the work in reviewable units with acceptance criteria. §11 is behaviour/cost. **§12 is repo traps that have already cost this project real time — read it before opening a PR.** §13 is out of scope. §14 needs a human (Matt).

Where this doc and the code disagree, **the code wins** — flag it rather than forcing the doc's shape.

---

## 1. What this feature is

Adding a product to PMQs today starts by demanding an `org/repo`. `api/products.py::add_product` runs `products.parse_repo_ref(repo)` and returns a 400 re-render if it can't parse one; `models.Product` makes `org` and `repo` `NOT NULL` and keys the whole row on `UniqueConstraint("org", "repo")`. GitHub isn't just the first field — it's the product's *identity*.

That made sense when repo evidence was the only signal. It isn't anymore. News ingestion is live, and the onboarding-research wave already makes the **website** the inviting first move: paste a URL, PMQs reads it, drafts the profile and watchlist, and the daily new-questions list fills from news relevance. For a whole class of PM — a product marketing manager on Asana + Google Docs, say — GitHub is at most an *outcome target* (the occasional Issue pushed to devs), never the input. Forcing a repo up front asks that PM for the one thing they don't have before PMQs has proven itself.

This feature makes the repo **optional**. The on-ramp becomes primarily about the PM's **website and product details**; GitHub is demoted to *the first optional connector* — a data source you can attach, not a precondition for existing. A product with a website and no repo is a first-class product: it generates questions from news, runs war rooms, produces outcomes. It simply skips the structural-repo pass until a repo is attached.

**What this is *not*:** it is not the connector framework. We are not building a generic "data sources" abstraction, a connector registry, or a second connector. We are loosening one hard-coded assumption (repo = identity) and reframing the repo field as the first of an eventual set. Naming ("connector" / "signal" / "data source") is deliberately left open — §9, §14.

---

## 2. The user flow

```
Add Product form
  ├─ Website:      https://…           (the research input — leads)
  │     └─ [Research this site]         (drafts the fields below)
  ├─ Display name / Watchlist / Profile ← reviewed, saved
  │
  ├─ ── Connect a repository (optional) ──
  ├─ Repository:   org/repo             (OPTIONAL now; blank is fine)
  │       • blank        → website-only product, created immediately
  │       • org/repo      → also attaches the GitHub structural source
  │       • malformed     → inline error (a typo, not an omission)
  │
  └─ POST /products  ──► create + persist watchlist/profile ──► seed pass
                          (structural seed runs only if a repo was given)
```

The only *visible* change from today is that Repository moves below the website/details block, gets an "optional" affordance, and no longer blocks submit when empty. The rest of the form is unchanged.

---

## 3. What "optional" means precisely

Three states, and the rules that separate them:

| Repo field on submit | Behaviour |
|---|---|
| **empty** | Create a website-only Product. `org`/`repo` are `NULL`. Slug derives from nickname → display name → website host → `"product"`. No `(org, repo)` dedup (there's no key to dedup on); always a fresh row. No structural seed pass — the inbox seeds from news on the next Refresh. |
| **`org/repo` (valid)** | Exactly today's behaviour: `parse_repo_ref` → `get_or_create_product` resolves-or-creates by `(org, repo)` (shared-Product case intact), structural seed pass runs against that repo. |
| **non-empty but malformed** | Inline 400 re-render, reviewed fields preserved — a typo is not an intentional omission. Preserves `test_add_product.py::test_malformed_repo_rerenders_the_form_inline`. |

The distinction that carries the whole feature: **empty repo is valid; malformed repo is an error.** Everywhere the code currently treats "no repo" as "fall back to the default repo," it must now treat a repo-*less product* as "there is no structural source here" (§5).

---

## 4. The data-model change (the one real piece of surgery)

Everything else is wiring; this is the schema.

**`models.Product` (`pmqs/models.py`):**
- `org` and `repo`: `nullable=True`. They stop being identity and become "the attached repo, if any."
- **Leave `UniqueConstraint("org", "repo")` as is.** SQLite treats `NULL`s as distinct in a UNIQUE constraint, so any number of `(NULL, NULL)` rows coexist — website-only products don't collide. This is why no key redesign is needed.
- `full_name` property: return `""` (or `None`) when `repo` is unset, **not** the string `"None/None"`. Every caller that builds a `gh --repo` argument or a display string reads this.

**Migration (`pmqs/db.py::_apply_light_migrations`):** the existing DB has `org`/`repo` as `NOT NULL`; `create_all` won't relax that on an existing table, and SQLite can't `ALTER COLUMN … DROP NOT NULL`. Add an **idempotent table-rebuild** for `products`, modelled exactly on the existing `_migrate_outcome_active_to_retired_at` (create new table with the relaxed schema → `INSERT … SELECT` → drop old → rename). Guard it by reading `PRAGMA table_info(products)` and running only while `org`/`repo` still show `notnull=1`. Fresh DBs never hit it — `create_all` builds the nullable schema from the model. **Back up the file first in the migration comment's spirit; this is Matt's live dogfood DB.**

**`products.py`:**
- `_slugify` gains a safe fallback chain. Extract a `_base_slug(*, nickname, display_name, website, repo)` that tries `nickname → display_name → host(website) → repo → "product"`, so a repo-less product still gets a stable slug. (`_slugify(None)` currently throws.)
- `get_or_create_product`: make `org`/`repo` optional. When **both** are falsy, skip the `(org, repo)` lookup and **always create** (no natural key to resolve on), slug from the fallback chain. When present, behaviour is unchanged.
- `get_or_create_default_product` / `db.py::_backfill_default_product`: unchanged — the Phase-0 dogfood account still bootstraps against `config.AGENTOS_REPO`. A repo-backed default product is correct for Matt; the point is that *new* products need not be repo-backed.
- `product_display_name`: its `full_name` fallback now yields `""` for repo-less products — make sure the chain (`nickname → display_name → slug → full_name`) still lands on something non-empty. It does, as long as create always sets a `display_name` (it does: it defaults to the researched name, and for a bare website we can default to the host).

---

## 5. The latent bug this must fix: `None` is overloaded

Right now `repo=None` means two different things, and the refactor makes the collision load-bearing:

- **`refresh.py::_refresh_repo`** does `AgentOSClient(repo=repo).get_state() if repo else AgentOSClient().get_state()` — so `repo=None` runs the structural pass against **`config.AGENTOS_REPO`** (the default repo).
- **`api/inbox.py::_repo_for`** returns `None` for the legacy *unprefixed* mount, meaning "no product scope, use the default."

A repo-*less product* must not inherit "use the default repo" — that would scan `open-agentos/agentos-pmqs` and attribute its issues to the PMM's website-only product. So:

- `_refresh_repo` / `pipeline.seed_workspace` must **skip the structural pass entirely** for a product that has no repo, and report a distinct, honest banner state (see §7) — not silently fall through to the default.
- Give the refresh/seed path enough to tell the three cases apart: (a) legacy unprefixed, no product → default repo (unchanged); (b) product **with** a repo → that repo; (c) product **without** a repo → skip. The cleanest signal is to pass the resolved `Product` (or a `product_has_repo` boolean) down rather than only a `repo: str | None`, since `None` can no longer mean one thing.

This is the single easiest thing in the plan to get wrong, and it fails silently (green tests, wrong data). Add a test that a repo-less product's Refresh reports "no repo connected" and makes **zero** `gh` calls.

---

## 6. Create endpoint (`api/products.py::add_product`)

- Read `repo = (form.get("repo") or "").strip()`. **Empty is now a valid path**, not an error.
- If `repo` is empty: `created = True`; call `get_or_create_product(db, org=None, repo=None, display_name=display_name or host(website) or "product", nickname=nickname or None)`. Everything downstream (`ensure_membership`, `apply_product_config` on `created`, redirect to `/w/{slug}/settings?added=1`) is unchanged.
- If `repo` is non-empty: `try parse_repo_ref` → on `ValueError`, keep today's inline 400 re-render with `values=dict(form)` (preserves reviewed fields). On success, today's resolve-or-create + shared-Product `created` detection is unchanged.
- `seed_workspace(db, product)` stays the single call; it becomes a no-op-for-structural on a repo-less product (§7). News still seeds on the next Refresh, as today.
- `save_product_settings` (`api/settings.py`) + `products.update_product`: `repo` is already `Form(default="")`, and `update_product` already treats blank as "unchanged." Confirm blank stays "unchanged" (don't let a blank on edit *detach* a repo). Detaching a repo is a §14 question, not this PR.

---

## 7. Refresh & seed reporting

- **`pipeline.seed_workspace`**: `if product is None or not product.repo: return []` before building any `AgentOSClient`. A repo-less product seeds nothing structurally; the news pass on the next Refresh fills the inbox.
- **`refresh.py::_refresh_repo`**: when the scoped product has no repo, return a new `SourceResult` state — e.g. `"no_repo"` with detail "no repository connected — questions come from news" — and make **no** `gh` call. Wire the banner text in `web/render.py::_REPO_LINES` (the `_refresh_line` map at ~L590) so it reads as a *neutral* state (like `disabled`/`no_watchlist`), **not** an amber fixable error — a website-only product with no repo is working as intended, not misconfigured.
- Leave the news source path untouched. It already runs per-product against each product's own watchlist and self-stamps the right `product_id`.

---

## 8. UI reframe (`web/render.py::_product_settings_sections`, create block ~L1742)

Minimal, within `web/TEMPLATE-CONTRACT.md`:
- Reorder the create identity block so **Website + Research + Display name + Nickname** come first and **Repository last**, under a small divider/subhead like "Connect a repository (optional)".
- Change the Repository `hint` to say it's optional and what attaching it adds: "Optional. Connect a GitHub repo to pull structural signals (stale issues, label conflicts) into your questions. You can add this later." Drop any wording implying it's required.
- No new fields, no new JS. The research JS and template anchors are unchanged.
- Edit-mode Settings: the Repository field stays (a product *can* have a repo); if it's blank, show the same optional framing. The news-status line already explains the news side.

Update `test_add_product.py::test_create_mode_posts_to_products_and_says_add` if it asserts field order; keep the `name="repo"` assertion (the field still exists, just optional).

---

## 9. The Phase-2 seam (named, then parked)

This refactor deliberately stops at "repo is optional." It does **not** build:
- a `Connector`/`Source` model, registry, or per-source config rows,
- a second connector (Asana, Jira, Linear, telemetry, …),
- a generic "add a data source" UI.

But it should leave the seam clean so Phase 2 is an extension, not a rewrite:
- The structural-repo pass in `refresh.py`/`triggers/*` is already the *shape* of a connector: a scheduled deterministic pass that emits candidate questions for a product. Phase 2's "improve the GitHub on-ramp as a template" means factoring that pass behind a small interface (`sources_for(product) -> [Source]`, each with `refresh(product) -> SourceResult`) so news and repo become two instances and a third slots in. **Do not do this now** — just don't wire anything in §5–§7 that would block it (passing the `Product` down, and the neutral `no_repo` state, both help).
- Vocabulary is unsettled (§14). Until Matt picks a term, code comments should say "signal source" as a placeholder and avoid minting a user-facing noun in the UI beyond "repository" / "connect a repo."

---

## 10. Work breakdown (issues → PRs)

File issues **inert/unlabelled** for Matt's triage. Each PR: **`base=main`, non-empty `closingIssuesReferences`, one issue per PR** — the intake-wild invariant (§12). Suggested split, in land order:

- **Issue A — schema: nullable `org`/`repo` + migration + slug fallback (§4).** Model change, the `products` table-rebuild migration, `_base_slug`, `get_or_create_product` optional-repo path, `full_name` null-safety. Pure data layer; no endpoint/UI change yet. Tests: repo-less create persists a row with `NULL` org/repo and a valid unique slug; two repo-less products coexist; existing repo-backed create/dedup unchanged; migration is idempotent against an already-migrated DB. **Land first** — everything else sits on it.
- **Issue B — refresh/seed skip for repo-less products (§5, §7).** `seed_workspace` guard, `_refresh_repo` `no_repo` state + banner line, pass the `Product`/`has_repo` down so `None` stops being overloaded. Tests: repo-less product Refresh makes zero `gh` calls and reports `no_repo` (neutral, not amber); repo-backed product Refresh unchanged. Depends on A.
- **Issue C — create endpoint accepts an empty repo (§6).** `add_product` empty-repo path; empty = create, malformed = 400 re-render. Tests: `POST /products` with no `repo` 303-redirects to the new product's settings; malformed `repo` still 400 with fields preserved. Depends on A.
- **Issue D — UI reframe (§8).** Reorder create block, optional affordance + hint, banner copy. Manual page-load check (no test asserts on markup — §12). Depends on C.

A → B → C → D. A is the gate; B and C are independent given A and can be parallel; D is last.

Rough suite delta: A adds ~4–6 tests, B ~3–4, C ~3, D 0–1. No existing test should need deleting — a couple need their assertions relaxed from "repo required" to "repo optional."

---

## 11. Behaviour & cost bounds

| Situation | Behaviour |
|---|---|
| Add product, website only, no repo | Product created immediately. Zero `gh` calls, zero structural spend. Inbox fills from news on next Refresh. |
| Add product with a valid repo | Exactly today: resolve-or-create by `(org, repo)`, structural seed pass runs. |
| Add product, malformed repo | Inline 400, reviewed fields preserved. No product created. |
| Refresh a repo-less product | News pass runs; structural pass skipped with a neutral "no repository connected" line. No `gh` call. |
| Two PMs add the same website (no repo) | Two separate products (no `(org,repo)` key to share on). Sharing repo-less products is a §14/invites concern, not this work. |
| Existing repo-backed products | Untouched. `config.AGENTOS_REPO` default product still bootstraps for the dogfood account. |

No new LLM or network cost is introduced anywhere — this refactor only *removes* a forced structural call for products that have no repo.

---

## 12. Repo traps (read before opening a PR)

- **The intake-wild invariant.** Every PR needs `closingIssuesReferences` non-empty → **`base=main` AND a real issue to close**. A stacked PR (`base != main`) links zero issues; a PR with no issue links nothing. Agent Intake then classifies it `source:wild` and loops, spawning stub issues (has happened twice, ~11 + 1 stubs). **This docs PR too** — open it against an inert tracking issue. Verify via the GraphQL `closingIssuesReferences` field, and re-query a few seconds after opening (indexing lags).
- **The `products` migration touches live data.** It's a table rebuild on Matt's dogfood DB. Make it idempotent (skip when `org`/`repo` already nullable), and don't run it inside the same transaction as anything else. Mirror `_migrate_outcome_active_to_retired_at` exactly — it's the working precedent for a SQLite rebuild here.
- **`None` was overloaded — don't re-merge the two meanings (§5).** "Legacy unprefixed → default repo" and "product has no repo → skip" must stay distinct. A test asserting zero `gh` calls for a repo-less product is the guard.
- **The app template is production code spliced by regex.** `render.py` injects into `app.html` via anchored patterns (`web/TEMPLATE-CONTRACT.md`); **no test asserts on the markup**, so it can break with the suite green. Keep the create-block reorder within the settings-sections region and **load the create form in a browser** before calling it done.
- **CI now runs pytest (#79 resolved by PR #149).** "Suite green" is CI-backed on push + PR now — but the markup-splice gap above still isn't covered by any assertion, so still load the page.
- **Keys never touch logs or responses.** Unchanged here, but the research endpoint stays server-side-only; don't add repo/website echoes to any response while touching these files.

---

## 13. Out of scope

- Any generic connector/source framework, registry, or second connector (§9 — Phase 2).
- Detaching a repo from an existing product via the edit form (blank-on-edit stays "unchanged"). §14.
- Sharing/deduping repo-less products across PMs (waits on invites).
- Repo *discovery* from the website (the onboarding spec already ruled this out, decision 12.1).
- Renaming the `/api/workspaces` route or the `workspace`/`session` naming collision.
- Widening the `(org, repo)` dedup key for a real Org boundary (Phase 5 auth).

---

## 14. Needs a human (Matt)

1. **The noun.** "Connector" vs "signal" vs "data source" — pick one before Phase 2 puts it in the UI. Until then, code says "signal source" internally and the UI says "repository."
2. **Detaching a repo.** Should the edit form let a PM *remove* a connected repo (blank the field to detach), or is a repo write-once-per-product until Phase 2? Current plan: blank-on-edit = unchanged (can't detach). Confirm.
3. **Default product for a fresh hosted account.** The dogfood account bootstraps a repo-backed default (`config.AGENTOS_REPO`). For a real new hosted user (Phase 5), the first product should probably be website-led with no default repo — flag for the Phase 5 auth work, not now.
4. **Neutral vs prompt.** For a repo-less product, do you want the Refresh banner to *quietly* say "no repo connected," or to gently *invite* connecting one ("Connect a repo to add structural signals")? Plan ships the quiet version; the invite is a one-line copy change if you'd rather nudge.
