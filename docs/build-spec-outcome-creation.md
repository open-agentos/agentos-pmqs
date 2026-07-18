# PMQs — Build Spec: Outcome Creation (the proof step)

_Last updated: 2026-07-18_

## 0. How to use this document

- **Code wins.** Where this plan and the code disagree, the code is the source of truth — flag the discrepancy in the PR, don't silently "fix" the plan by forcing the code to match it. (Same §0 rule as the shared-outcomes plan; it has already applied repeatedly.)
- **Reduce complexity.** Standing directive on this product. Prefer deriving over storing, reusing an existing pattern over inventing one, and shipping the smallest thing that removes the confound. Every new column, tab, or endpoint here must justify itself against that bar.
- **Do not regress the baseline.** The suite is green today; every wave ends green. There is still no pytest CI (see #79), so "green" is a local claim — run it.
- **Intake-wild invariant.** Every PR needs non-empty `closingIssuesReferences`: base=main AND an issue to close. Verify with the GraphQL field before trusting it. A docs-only branch with no issue behind it produced stub #49 last time.

## 1. Why this work exists

Outcomes are the **proof** that everything higher up the funnel — the inbox, the war room, the position document — actually drove thoughtful, informed product management. They are deliberately *not* dominant in the UI. But without them PMQs collapses into a think-tank: stimulating, and not durable or sustainable over time.

The unit of durable value is not a cleared inbox. It is the thing a PM produces after facing a hard question: an Issue, a Policy, a Document, a Meeting, a new Question. A PM who walks out of a Workspace engagement and writes a document that would have taken them a day otherwise is the whole business case — it demonstrates that the context PMQs amasses and generates is worth paying for. The context is portable (a PM could paste it into any AI chat app); PMQs earns its place by making the step from *engagement* to *artifact* smooth, guided, and integrated, rather than leaving the PM to do it themselves elsewhere.

The corollary matters just as much. **A missing outcome is not automatically a sign the system is weak.** Sometimes a session genuinely warrants no artifact. But today we cannot tell that case apart from three failure modes we are responsible for:

1. The PM **didn't know how** to create the outcome.
2. The PM **didn't know what kind** of outcome to create.
3. The PM **didn't know where** the outcome ended up, so they couldn't find or trust it.

This spec removes those three confounds and makes absence legible, so that when an outcome doesn't happen we can believe it's a real signal about the question rather than friction in the tool.

## 2. Current state (what "underdeveloped" means concretely)

The plumbing exists; the experience does not. Verified in the repo as of this writing:

- **The outcome bar is fire-and-forget with a fake payload.** The five war-room buttons (`Raise issue`, `Save policy`, `Draft document`, `Schedule meeting`, `New question`) call `addOutcome(type, label)`. `render.py` overrides the template's demo handler with a real one — but it POSTs only `{type, title}`, and `title` is a **hardcoded demo string baked into the template button** (`'Mitigate #47 for adopt path'`, etc.). So in the live app, "Draft document" sends a fixed fake title and an **empty body**.
- **Nothing is generated from the session.** `outcomes/types.build_document(title, body)` stores whatever it's handed. The war room holds the entire decision context — conversation, position doc, evidence, product policies — and none of it reaches the artifact. The one place we already generate rich content from context is `position_doc.py`; the outcome path doesn't reuse it.
- **`pmqsPost` is a full-page form submit.** Clicking an outcome button navigates the browser to the endpoint, which returns JSON. **The PM literally lands on a raw JSON blob.** There is no review, no edit, no confirmation, and no way back to the room except the back button.
- **Only Issue has a destination.** Issue → GitHub (`push_question_to_issue`, gh CLI). Document, Meeting, Policy, Question become hosted-store rows with no destination, no link, no export. "Maybe it's a GitHub issue or a meeting or a Jira task" — only the first is served.
- **Absence is invisible.** Leaving a war room without an outcome writes nothing. We can't distinguish "no decision needed yet" from "couldn't produce the artifact."

The ledger, visibility rules, authorship, promotion, and the context-feed are all built and correct. This spec sits entirely on top of them.

## 3. The model of the fix

Reframe outcome creation from a **fire-and-forget button** to a four-beat micro-flow that **never leaves the war room**:

> **Suggest → Draft → Commit & Route → Receipt**

Each beat removes one confound. A fifth item makes absence legible.

- **Suggest** removes _"didn't know what kind."_
- **Draft** removes _"didn't know how."_
- **Commit & Route** serves _GitHub / Jira / meeting / export_.
- **Receipt** removes _"didn't know where it went."_
- **Legible absence** makes a null outcome a signal, not a mystery.

None of this makes Outcomes louder in the UI. It makes the existing bar do real work.

## 4. Behaviour specs

### 4.1 Suggest — the recommended outcome (removes "what kind")

The war-room partner already probes the PM toward a decision. When the conversation has produced something decidable, it should **name the outcome**: a type, a draft title, and a one-line rationale.

- Surfaced as a **recommended-outcome chip** in the outcome bar, e.g. _"Looks like a Policy: 'Flag template drift before any upgrade' — because you just committed to a standing rule."_ The five typed buttons stay; the suggestion sits above them as the fast path.
- Type selection is an **LLM triage** over the session (conversation + position-doc verdict + evidence), reusing the lens machinery's judgment style — not a hardcoded keyword map. A session can warrant more than one; suggest the strongest, offer the rest.
- The PM can **accept** the suggestion, **pick a different type**, or **start blank**. Accepting jumps straight to Draft with the title pre-filled.
- Cost discipline: the suggestion is cheap. It piggybacks on the war-room reply where possible (no extra round-trip per message), or runs once on an explicit "wrap up" action. It must **never** auto-fire an outcome — suggestion is not creation.

### 4.2 Draft — generate from context, then let the PM edit (removes "how")

Choosing a type **generates real content from the full session context** and renders it into an editable **Draft** artifact tab in the war-room pane. It is not stored yet.

- One LLM call, reusing the `position_doc.py` pattern (single round-trip, strict schema, graceful fallback). Inputs: conversation history, the session's position doc if present, evidence, and the Product's active policies via the existing `context_feed` (so drafts already respect standing rules).
- Per-type generation shape:
  - **Issue** → `title` + `body` (problem statement, acceptance criteria, evidence links). Feeds the existing `push_question_to_issue` body path.
  - **Document** → `title` + `body` (the briefing/PRD/analysis the engagement produced).
  - **Meeting** → `title` + `agenda` (the agenda is the artifact; a calendar link is optional and downstream).
  - **Policy** → `text` (free-form standing rule, per product-design.md — "similar to Memory," not a schema).
  - **Question** → `title` + `body` (a sharper question for the inbox).
- **The PM reviews and edits before committing.** This is the seam that turns "the system wrote something" into "the PM decided something." The draft is editable in place.
- **Fallback never blocks.** If the LLM is unavailable, the Draft tab opens with an empty, editable stub and a clear "[draft not generated — write it yourself]" marker. The PM can still commit. (Phase 1 degrade-gracefully discipline.)
- **Draft persistence:** drafts are ephemeral until committed — held in the Draft tab client-side, not written to a table. Only committed outcomes persist. (See §7 decision: whether to persist an in-progress draft on the session like `position_doc` is deferred until there's evidence PMs lose work mid-draft.)

### 4.3 Commit & Route — one destination per type (serves GitHub / Jira / meeting / export)

On **Confirm**, the outcome is persisted to the ledger **and** routed to its destination through a small connector seam.

- **Issue** → a **tracker connector**, not a hardcoded GitHub call. Introduce a `tracker` interface with one method (`create_issue(title, body, labels) -> {url, ref}`). GitHub (the current gh-CLI path) is the default and only real implementation at launch; **Jira is a stub behind the same interface** so "or a Jira task" has a home without building the integration now. The chosen tracker comes from Product Settings (defaults to GitHub). Policies still **never** route to a tracker.
- **Document** → hosted store **plus export affordances**: copy-to-clipboard, download `.md`, open-in-new-tab. This is the portability value made real — the artifact is yours and drops cleanly into any doc or chat tool. No Google Docs dependency (product-design.md).
- **Meeting** → hosted agenda (the durable artifact) + optional `calendar_link` passthrough (already on the payload). No calendar dependency.
- **Policy** → hosted store, private to the Product, with confirmation that it now feeds agents via the context-feed.
- **Question** → back into the inbox (existing path), product-scoped.

The connector seam is deliberately thin: one interface, one live impl, one stub. It exists so the Issue path stops being GitHub-shaped in the code, not to build multi-tracker support today.

### 4.4 Receipt — say what was made and where it lives (removes "where")

Replace "navigate to raw JSON" with an **inline receipt that stays in the war room**:

- A confirmation line naming the outcome, its type, and its location, with a **direct link**: the GitHub/Jira URL for Issues, the export/open action for Documents, the calendar link for Meetings, the inbox entry for Questions, the ledger row for everything.
- **Every outcome lands in the ledger**, and every ledger row resolves to a location. The ledger is the durable answer to "where can I find it." The receipt is the immediate answer.
- The session-stats strip's live outcome count updates from the real commit (it already exists), so the PM sees the proof accrue without leaving the room.

This requires the outcome endpoints to return a resolvable location and the client to render it in place rather than form-submitting to a JSON page. That client change (fetch + inline render, no navigation) is the single biggest UX win in this spec.

### 4.5 Legible absence — make a null outcome a signal

So that a missing outcome stops being ambiguous:

- When a PM leaves a war room **without** committing an outcome, offer a one-tap close reason: _no decision needed yet_ / _decided, nothing to record_ / _couldn't get what I needed_. Optional, dismissable, never a gate.
- Record session → outcome conversion. The _"couldn't get what I needed"_ bucket is the one that means the tool failed; the others mean the tool worked and the answer was legitimately "nothing to file." This is what lets us honour the premise that absence isn't automatically weakness — we can finally tell the cases apart.
- No new stakeholder dashboard (product-design.md killed "State of the Product" for now). This is a private signal on the session, surfaced at most as a quiet stat.

## 5. Schema

**Target: no new columns.** Location is derivable:

- **Issue** already carries `github_ref`. For a non-GitHub tracker, store the returned URL in the same field (it's a tracker ref, not a GitHub-specific one) — the name is historical; flag it, don't migrate it.
- **Document / Meeting / Policy / Question** resolve to a ledger-relative location computed from `type` + `id`. Export URLs for Documents are generated on demand, not stored.

**Decision deferred, not taken (see §7):** if a second real tracker (Jira) ever ships, a generic `destination_ref` + `destination_kind` pair may be worth it so the field name stops lying. Until then, reuse `github_ref` and flag the naming in code comments. This keeps the wave schema-free.

## 6. Work items (waves)

Ordered so each wave is independently shippable and felt.

### Wave 1 — make the real path real (highest value, no LLM, no schema)
1. **Client: fetch-and-render instead of form-submit.** `addOutcome` becomes a `fetch` that renders the receipt inline and updates the ledger/stat, never navigating to JSON. Removes the "land on a JSON blob" defect outright.
2. **Receipt payload.** `create_typed_outcome` and `push_question_to_issue` return a resolvable `location` (URL or ledger ref) and a display title. The client renders it.
3. **Kill the hardcoded demo titles.** The buttons stop shipping fake `title` strings; an empty type opens the Draft flow (Wave 2) or, until that lands, a minimal title input.

### Wave 2 — Draft from context (removes "how")
4. **Draft generator** (`outcomes/draft.py`), one LLM call, reusing the `position_doc` pattern and `context_feed`. Per-type shapes from §4.2. Graceful empty-draft fallback.
5. **Draft artifact tab** in the war-room pane: generated content, editable, with Confirm / Discard. Commit posts the edited content to the existing typed-outcome endpoint.

### Wave 3 — Route & destinations (serves GitHub / Jira / export / meeting)
6. **Tracker connector seam.** Extract `tracker.create_issue`; GitHub as the live impl, Jira as a stub raising a clear "not configured." Tracker choice from Product Settings, default GitHub.
7. **Document export.** Copy / download `.md` / open-in-tab on any Document outcome (in the ledger and the receipt).
8. **Meeting calendar-link passthrough** surfaced in the receipt (field already exists).

### Wave 4 — Suggest & legible absence
9. **Recommended-outcome suggestion** (§4.1): type + draft title + rationale, piggybacked on the war-room reply or a "wrap up" action.
10. **Session close reason + conversion signal** (§4.5).

Waves 1–2 alone remove two of the three confounds and fix the worst UX defect. Ship them first; 3–4 compound the value.

## 7. Decisions requiring a human

1. **Suggestion trigger cadence.** Piggyback the type-suggestion on every war-room reply (richer, more tokens) vs. run it once on an explicit "wrap up" action (cheaper, less magical)? Recommendation: explicit wrap-up for MVP, matching the cost discipline that keeps the lens pass behind a button.
2. **Draft persistence.** Ephemeral client-side draft (recommended, zero schema) vs. persist an in-progress draft on the session like `position_doc` (survives reload, costs a column + write paths). Only worth it if PMs report losing drafts.
3. **`github_ref` naming.** Reuse it for a Jira URL and flag the lie (recommended, no migration) vs. add `destination_ref`/`destination_kind` now. Defer until a second tracker is real.
4. **Jira depth.** Stub-only behind the seam for now (recommended) vs. a real integration. The seam makes this a later, isolated call.
5. **Close-reason prompt.** Always offer on exit-without-outcome vs. sample it vs. off by default. It must never feel like a gate.

## 8. Out of scope

- A stakeholder-facing outcome dashboard / "State of the Product" (explicitly deferred in product-design.md).
- Real Jira/calendar integrations (seam and passthrough only).
- Google Docs as a Document destination (no dependency beyond login).
- Auto-committing outcomes without PM confirmation (suggestion is not creation).
- Any change to visibility, authorship, promotion, or the context-feed — all built and correct; this spec sits on top of them.

## 9. Repo conventions and traps (carried forward)

- The app template (`pmqs/pmqs/web/templates/app.html`) is **production code**; `render.py` splices into it via regex anchored on its markup, and no test asserts on that markup, so it can break with CI green. If a new Draft tab or receipt region is added, add/extend a `TEMPLATE-CONTRACT.md` anchor and a render test.
- `members.current_member_id()` is the Phase 5 auth seam — route any "who committed this" through it, don't re-derive.
- Fail open, never suppress: a fallback that can't generate a draft must still let the PM write and commit one. Losing an outcome to a silent failure is the one unrecoverable error here.
- One commit per task, PR base=main with a real closing issue, verify `closingIssuesReferences` non-empty before trusting the link.
