"""pipeline.py — Phase 1 generation pipeline glue.

Orchestrates: run triggers -> frame each hit (LLM stub) -> dedup batch (LLM stub) ->
persist Questions -> score. Keeps triggers deterministic and LLM passes decoupled, per
spec. A framing failure never drops a trigger hit.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import framing, repository, scoring
from pmqs.dedup import dedup
from pmqs.triggers import ALL_TRIGGERS


def run_triggers(state: dict[str, Any], triggers=None) -> list[dict[str, Any]]:
    triggers = triggers if triggers is not None else [T() for T in ALL_TRIGGERS]
    hits: list[dict[str, Any]] = []
    for trig in triggers:
        hits.extend(trig.run(state))
    return hits


def hits_to_candidates(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Frame each hit into a Question candidate. Framing never raises (stub-safe)."""
    candidates = []
    for hit in hits:
        framed = framing.frame(hit)
        candidates.append(
            {
                "title": framed["title"],
                "description": framed["description"],
                "lens_tags": hit.get("lens_tags", []),
                "evidence": hit.get("evidence", []),
                "source": "system",
            }
        )
    return candidates


def generate(db: OrmSession, state: dict[str, Any], triggers=None, *, workspace_id: str | None = None) -> list:
    """Full pass: triggers -> frame -> dedup -> persist -> score. Returns Questions."""
    hits = run_triggers(state, triggers)
    candidates = dedup(hits_to_candidates(hits))
    questions = []
    for cand in candidates:
        q = repository.create_question(
            db,
            title=cand["title"],
            description=cand["description"],
            lens_tags=cand["lens_tags"],
            evidence=cand["evidence"],
            source=cand["source"],
            status="proposed",
            workspace_id=workspace_id,
        )
        score, dims = scoring.score_question(q)
        repository.set_question_score(db, q.id, score, dims)
        questions.append(q)
    return questions


def seed_workspace(db: OrmSession, workspace) -> list:
    """Run one immediate structural-lens pass for a freshly-created Workspace (#54).

    Reuses the same trigger/frame/dedup/score pipeline as the daily scheduled batch --
    this just fires it once, synchronously, at Workspace-creation time, so a newly
    added product's inbox isn't empty until tomorrow's run. Reads live substrate state
    from the Workspace's own Product (not config.AGENTOS_REPO), which is what makes
    this correct for a second/third product rather than re-scanning the default repo.

    Framing/dedup are LLM-backed but PMQS_LLM_MODE=off (tests, and any deployment
    without a configured provider) keeps them deterministic stubs -- a fetch failure
    against the target repo surfaces as an empty seed rather than blocking Workspace
    creation.
    """
    from pmqs.agentos_client import AgentOSClient, AgentOSClientError
    from pmqs import products as products_mod

    product = products_mod.get_product(db, workspace.product_id)
    if product is None:
        return []
    try:
        state = AgentOSClient(repo=product.full_name).get_state()
    except AgentOSClientError:
        return []
    return generate(db, state, workspace_id=workspace.id)
