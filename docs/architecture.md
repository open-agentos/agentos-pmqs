# Open AgentOS — Substrate Architecture Reference

[github.com/open-agentos/agentos](https://github.com/open-agentos/agentos) is a
GitHub-primitives agent orchestration system: Issues, Labels, and Actions as
substrate, with per-role GitHub App identities. PMQs is a product layer built on top
of this substrate — see `product-design.md` for what PMQs does with it.

## Facts an implementing agent needs

- **Testbed repo:** `agentos-pmqs` — validated end-to-end across both issue-led and
  PR-led paths. This is the repo PMQs Phase 0 dogfoods against.
- **CLI tooling:** `agentos init`, `agentos apply`, `agentos upgrade`, `agentos verify`.
  `agentos state --json` is also available for structured state reads.
- **GHA secrets convention:** `{ROLE}_APP_ID` / `{ROLE}_PRIVATE_KEY`.
- **Template tree:** authoritative source is `bootstrap/templates/`; the top-level
  `templates/` directory must stay byte-identical to it.
- **PAT auth pattern:** uses an askpass shim — credentials are never written to disk.

## ⚠️ Standing hazard — read before touching `agentos-pmqs`

**Do not run `agentos apply` or `agentos upgrade` against `agentos-pmqs`** until the
adopt→upgrade data-loss bug is fixed upstream (tracked as ledger item / issue #47).
Running either command in its current state would silently overwrite the customized
`AGENT.md` files in that repo. This applies to any agent (human or Claude) working in
this codebase — treat it as a hard rule, not a suggestion.

## Known upstream defects (context, not all blocking)

- Masked-log corruption (`***` artifacts committed as code)
- Missing permissions blocks
- **Data-loss bug in adopt→upgrade path** — the one above, deferred, blocking
- Stale PyPI release (was 1.1.0 vs 1.2.3 — fixed via trusted publisher reconfiguration)
- Missing env contracts in role templates
- Missing per-role push identity
- Silent `LLM_API_KEY` no-op
- Orphaned observability layer

Upstream PRs already opened: #55 (masked-log corruption fix), #56 (workflow token
permissions). Remaining open PRs to track: #53 (receipt rewrite), #46 (preflight),
#50 (`LLM_API_KEY`), #48 (env contract), #49 (push identity), #51 (observability).

## Prior milestones (context)

- "Wild lane" (YOLO/PR-led intake) implemented and validated with an archaeologist
  role deliberately given no GitHub App identity (security decision — pure function).
- Planner agent implemented with an approval gate (dispatch-time permission check,
  not a label-guard).
- `agentos upgrade` subcommand built; versioning misalignment fixed across spec,
  PyPI, and bootstrap templates.
- Repo renamed from `open-agentos/spec` to `open-agentos/agentos`; published to PyPI
  as `open-agentos-cli`.

## Predecessor system (context, not architecture PMQs depends on)

Before AgentOS was extracted/open-sourced, an internal system called 3Qs Ops ran under
the `3qs-oss` org: builder/reviewer/docs/watcher agents, 140+ real agent runs against
GitHub issues, JSONL run-record telemetry (schema v1–v6), GitHub Projects v2 as a
control plane. Notable finding: 43% of weekly spend went to errors/bad loops; $0.61
per shipped issue vs. $3.43 blended. Useful background on why AgentOS is shaped the
way it is; not something Phase 0–1 implementation needs to touch.
