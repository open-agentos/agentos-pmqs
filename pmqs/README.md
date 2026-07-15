# PMQs

> ## ⚠️ STANDING HAZARD — READ FIRST
> **Never run `agentos apply` or `agentos upgrade` against `agentos-pmqs`.**
> The adopt→upgrade path has an unfixed data-loss bug (upstream issue #47) that
> silently overwrites the customized `AGENT.md` files in that repo. This is a hard
> rule for every agent (human or AI) working in this codebase — not a suggestion.
> See `../docs/architecture.md`. There are **no** `agentos apply`/`upgrade` calls
> anywhere in this codebase, and a test (`tests/test_no_hazard.py`) enforces that.

PMQs is a web interface for product managers, built as a product layer on top of
[Open AgentOS](https://github.com/open-agentos/agentos). It reads the AgentOS
substrate (Issues/Labels/PRs) for a repo, generates ranked decision questions, and
pushes chosen outcomes (Phase 1: GitHub Issues) back.

This is the Phase 0 → Phase 1 build. See `../docs/build-spec-phase-0-1.md`.

## Deviation from spec — AgentOS read transport

The spec assumes `agentos state --json` returns repo Issues/Labels. The installed
AgentOS CLI (`open-agentos-cli`) exposes only `init/setup/apply/verify/token` — there
is **no `state` subcommand** that reads live GitHub state. Per the spec's guidance to
flag integration-surface findings rather than block, Phase 0 reads Issues/Labels via
the `gh` CLI (GitHub API) directly. `agentos_client.AgentOSClient.get_state()` keeps a
stable, swappable interface: if a real `agentos state --json` lands upstream, only the
private fetch method changes. See `agentos_client.py`.

## Run

```bash
cd pmqs
uv venv && source .venv/bin/activate
uv pip install -e ".[test]"

# Point at a local agentos-pmqs checkout (defaults to the repo one level up)
export PMQS_AGENTOS_REPO=open-agentos/agentos-pmqs

uvicorn pmqs.api.app:app --reload
# open http://127.0.0.1:8000/
```

`gh` must be authenticated (`gh auth status`).

## Tests

```bash
pytest -q
```
