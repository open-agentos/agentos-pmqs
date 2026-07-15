# PMQs — Product & UX Design Record

PMQs is a web interface for product managers, built as a product layer on top of
[Open AgentOS](https://github.com/open-agentos/agentos) (a GitHub-primitives agent
orchestration substrate — Issues, Labels, Actions). See `architecture.md` for the
substrate this sits on.

## Positioning & business model

- One codebase, pluggable auth/deployment: self-hosted OSS for teams; enterprise-hosted
  version where IT owns deployment and the PM just logs in (Figma/Notion/Linear-style
  cloud+self-hosted split).
- Hosted/subscription is the primary monetization target. Codebase stays open source;
  the *deployment* is proprietary. Not over-optimizing for self-hosters' devops needs
  at this stage — e.g. news ingestion infra is designed hosted-first.
- Explicitly out of scope for now: a "State of the Product" stakeholder-facing dashboard.
  PMQs is scoped to one PM's private decision loop, not reporting. May emerge later,
  organically, from the Outcomes ledger.

## Core interface model

Three top-level modes:

1. **Inbox** — a short ranked list of items needing human decision (not a feed).
   - No "overnight summary" opener, no "Needs a decision" header — just the list.
   - Saved items stay integrated in the same ranked list, slightly visually distinct,
     not moved to their own section.
   - Quiet visual filter selector (not a heavy dropdown).
   - Quick-add: PM can inject their own question directly, not just react to
     system-raised ones.
   - All items — system-raised, saved, PM-added — carry multi-dimensional scoring so
     they can be surfaced/hidden/filtered by current PM concern.
   - Left-rail health metrics strip (cost, error rate) — static, not animated.

2. **Workspace** — war-room and doc-generation modes share one interface shell.
   - War-room: multi-pane IDE-style — conversation plus living documents/artifacts/
     charts (canvas-style), but decision-oriented: PM leads, chooses, decides. Not
     open-ended collaborative refinement.
   - Challenge/probe mechanic: probes and challenges the PM's thinking without playing
     as adversarial "counter-argument theater."
   - Doc-generation mode: same shell, task-completion oriented (PRDs, competitive
     analysis, etc.), using full available context.
   - Sessions can branch — a session can raise multiple new questions/decisions, not
     just resolve one.
   - Artifact tabs: **Position document**, **Evidence** (source issues/PRs/runs an
     answer is grounded in), **Impacts** (cost is one type among several), **Proposed
     questions** (system-proposed candidates, with "Add to inbox").
   - "This session" indicator — Claude Code session-indicator style (activity + cost
     of the current session).

3. **Outcomes** — a dedicated top-level ledger view.
   - Running record of everything produced, with a summary strip (counts by type).
   - Success is measured by outcomes produced, not by inbox-cleared.

## Question generation

- System proactively drafts candidate questions in the background — not just a
  byproduct of active war-room sessions. These feed the Inbox directly.
- Time-boxed: a fresh batch each day, not an indefinite accumulating queue. PMs are
  more likely to silently ignore unhelpful questions than actively dismiss them, so
  bounded daily regeneration avoids relying on dismiss-rate as a signal.
- **8-lens taxonomy** (treated as sufficient/complete for question generation across
  products): competitive positioning; growth/adoption signal; unit economics/margin;
  risk & exposure; roadmap tradeoff/sequencing; quality/reliability; org/execution
  drag; narrative/external positioning.
- Lens weighting (how much each lens matters for a given product) uses sane defaults,
  configurable per-product in settings. Inferring weights from PM behavior is a later
  phase, not MVP.
- **Triggers** split into two kinds:
  - *Structural/threshold* — cheap, deterministic repo queries (stale-issue age,
    label conflicts, error/cost deltas). Each structural lens owns its own scheduled
    query against Issues/Labels/PRs/Actions, like a saved search. No LLM needed to
    decide if a threshold hit matters.
  - *Interpretive* — an LLM pass, needed for news relevance and judgment calls.
  - A light LLM framing pass may still sit on top of a structural trigger (explaining
    *why* a cost delta happened) without making the trigger itself interpretive.
  - Watch item: risk of the system drifting toward LLM-triggers-for-everything over
    time. Using different models for different trigger/activity types is a candidate
    mitigation, deliberately deferred past MVP.
- Dedup/collision across lenses is an **LLM judgment call**, not deterministic — it
  identifies when candidate questions from different lenses are really about the same
  underlying thing. An LLM also **triages which of the 8 lenses are relevant** to a
  given session/batch topic, rather than always firing all 8 or hardcoding a
  topic-to-lens mapping.
- Question objects have a **Title** and a **Description** field — the latter holds
  fuller explanation, dedup/merge reasoning, links to source material, and can include
  raw thinking/reasoning that formulated the question.
- **Scoring**: unified approach — one multi-dimensional scoring formula (lens weight
  as one dimension) ranks all candidates, new and saved alike. No separate ranking
  system for saved items. *(Confirmed direction as of the Phase 0/1 build spec.)*
- The 8 lenses feed war-room session setup by assembling multiple points of view to
  frame the deep-dive (not just spawning follow-ups) — same lens machinery does triple
  duty: daily inbox generation, war-room session framing, and Position Document
  for/against structure.
- Opening a war-room session triggers a **fresh, scoped lens pass** specific to that
  session's topic, rather than reusing a continuously-running generator.
- Per-lens (not single general-pass) research is the confirmed direction for
  war-room deep research.
- **Open watch-items, not solved for MVP:**
  - Whether some macro/strategic questions are too big for the 8-lens taxonomy even
    combined. MVP approach: let broad topics pull in more lenses; no macro-detection
    mechanism.
  - Possible escalation mechanism: an "Agent Debate" mode on a war-room session — a
    range of agents with different perspectives debate and vote, becoming another
    input for the PM (like a select committee). Too complex for MVP; leading candidate
    shape for the eventual synthesis layer.

## Position documents

- Ever-present "generate position document" option per issue/decision — a full
  research report so the PM is fully informed without hunting for pieces or relying
  on their own research quality.
- Modeled on the **California Voter Guide** format: plain-language summary, "what
  your vote means" yes/no consequence framing, neutral analyst background/
  fiscal-impact section, argument for and argument against, each with a rebuttal.
- Generated **on-demand only**, not proactively — thorough and expensive, so only
  built when the PM actually opens the question.

## Outcomes system

- War-room sessions need **typed outcomes** to make decisions concrete. A session can
  produce more than one.
- Outcome types:
  - **Issue** — new GitHub Issue. The only type promoted to actual GitHub substrate.
  - **Policy** — new durable/standing rule. Starts as unstructured free-form text used
    as context for agent behavior and conversation, not a structured rule schema
    (at least initially). Conceptually similar to "Memory" in agent-harness parlance.
    **Must never be stored in GitHub** — private to the customer, hosted-store only.
  - **Document** — stored in the hosted store (same treatment as Meeting agendas for
    v1). Google Docs is not a dependency for this outcome type.
  - **Meeting** — with agenda. Agenda content stored in the hosted store (useful
    context for downstream AI purposes). A link to the agenda can optionally be
    attached to an actual calendar meeting to help create it, but Google Calendar is
    not a dependency.
  - **Question** — new inbox item for later.
- All non-Issue outcome types feed agents through **one unified context-feed
  mechanism** (same plumbing used for Policies, news items, meeting agendas,
  documents) — not bespoke per-type integration.
- For MVP, Issue outcomes use a **"push to GitHub" action**, not full shared-credentials
  GitHub integration — no per-customer repo/App-installation requirement at launch.
- Google Auth is scoped to login only — not a write-scope dependency for any outcome.

## Data sources & evidence model

- Two input types scoped for question generation and position documents:
  **industry/competitive news**, and **repos** (the AgentOS substrate — issues, PRs,
  telemetry).
- Raw news items are held in a **separate store outside the Issues substrate**
  (not labeled Issues) to keep Issues clean.
- Raw-versus-evidence line: raw material sits unjudged in staging; evidence is raw
  material explicitly bound to a specific question or decision.
- Proactive inbox questions carry a **minimal cited evidence pointer** (not
  evidence-free) — repo evidence uses direct receipts (Issue/PR/run ID); news evidence
  uses attributed-but-hedged citation. Position documents do the exhaustive
  evidence-promotion pass on demand.
- The **hosted store is the source of truth** for all five outcome types at MVP.
  GitHub and Google are optional *push targets*, not dependencies — except Issue
  outcomes, which do get pushed to real GitHub Issues.

## Mockup

- Built as a single self-contained HTML mockup: dark ink + warm-paper document panel,
  teal/brass/violet/sky accent colors per outcome type.
- File: **`pmqs/pmqs/web/templates/app.html`** — iterated across several rounds of
  feedback. Single self-contained file: open it directly in a browser, no build step.

> **This stopped being a mockup.** It began as `docs/pmqs-mockup.html`, a visual
> reference the Phase 0/1 build spec reused rather than redesigning from scratch. It is
> now the app's live template: `render.py` splices real data into it at request time, and
> PMQs cannot serve a page without it. It moved to `pmqs/pmqs/web/templates/app.html` to
> stop `docs/` from looking like a safe place to edit production code.
>
> Its markup is a load-bearing API — see `pmqs/pmqs/web/TEMPLATE-CONTRACT.md` before
> changing it.
- Theming note: an earlier UK Prime Minister's Questions ceremonial framing was
  explored and simplified away in favor of a plainer inbox + workspace model. The
  parliamentary reference (bounded, time-boxed session) resurfaced organically in the
  time-boxed proactive-question-generation decision above.

## Deployment sequencing (decided)

Phased, prioritizing shipping real code early over over-designing:

- **Phase 0** — single-tenant/no-auth, dogfooded on own account against `agentos-pmqs`.
- **Phase 0.5** — fake the hosted store with the simplest possible persistence
  (SQLite), not a full hosted-store service.
- **Phase 1** — repo evidence only (news deferred); Issue outcome type only.
- **Phase 2** — war-room + on-demand position docs.
- **Phase 3** — remaining outcome types (Policy, Document, Meeting).
- **Phase 4** — news ingestion.
- **Phase 5** — real auth + multi-tenant + hosted production.
- **Phase 6** — self-hosted OSS packaging (deliberately last).

See `build-spec-phase-0-1.md` for the concrete task breakdown of Phases 0–1.
