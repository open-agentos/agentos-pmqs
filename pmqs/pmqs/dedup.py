"""dedup.py — LLM dedup/collision pass (Phase 1 task 3).

LLM judgment call: given the day's batch of candidate Questions, identify pairs/groups
about the same underlying thing and merge them (merge reasoning -> surviving
Question's description).

The LLM judgment goes through pmqs.llm. If the LLM is unavailable or errors, a
deterministic heuristic stands in (token Jaccard over a threshold, or a shared
evidence ref) so the pipeline never breaks. Set PMQS_LLM_MODE=off to force heuristic.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pmqs import llm

log = logging.getLogger(__name__)

_SIM_THRESHOLD = 0.6

_SYSTEM = (
    "You decide whether two product-management questions are really about the SAME "
    "underlying issue and should be merged. Consider the topic and cited evidence, not "
    'just wording. Respond as JSON: {"duplicate": true|false}. No markdown.'
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _evidence_refs(cand: dict[str, Any]) -> set[str]:
    return {str(e.get("ref")) for e in cand.get("evidence", []) if e.get("ref") is not None}


def _llm_are_duplicates(a: dict[str, Any], b: dict[str, Any]) -> bool | None:
    """LLM judgment via pmqs.llm. Returns None on unavailable/error (fall back to heuristic)."""
    if not llm.is_enabled():
        return None
    user = (
        f"Question A:\n  title: {a.get('title')}\n  evidence: {sorted(_evidence_refs(a))}\n"
        f"Question B:\n  title: {b.get('title')}\n  evidence: {sorted(_evidence_refs(b))}"
    )
    try:
        result = llm.complete_json(_SYSTEM, user)
        if isinstance(result, dict) and "duplicate" in result:
            return bool(result["duplicate"])
    except Exception as exc:
        log.warning("dedup LLM call failed, falling back to heuristic: %s", exc)
    return None


def _are_duplicates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    verdict = _llm_are_duplicates(a, b)
    if verdict is not None:
        return verdict
    if _evidence_refs(a) & _evidence_refs(b):
        return True
    return _jaccard(a.get("title", ""), b.get("title", "")) >= _SIM_THRESHOLD


def dedup(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge near-duplicate candidate Questions. Distinct ones all survive.

    Each candidate: {title, description, lens_tags, evidence, source, ...}.
    Merge reasoning is appended to the surviving candidate's description.
    """
    survivors: list[dict[str, Any]] = []
    for cand in candidates:
        merged = False
        for surv in survivors:
            if _are_duplicates(surv, cand):
                surv["description"] = (
                    (surv.get("description") or "")
                    + f"\n[dedup] merged duplicate: {cand.get('title')!r} "
                    f"(evidence {sorted(_evidence_refs(cand))})"
                )
                # union lens tags + evidence
                surv["lens_tags"] = sorted(set(surv.get("lens_tags", [])) | set(cand.get("lens_tags", [])))
                seen = {str(e.get("ref")) for e in surv.get("evidence", [])}
                for e in cand.get("evidence", []):
                    if str(e.get("ref")) not in seen:
                        surv.setdefault("evidence", []).append(e)
                merged = True
                break
        if not merged:
            survivors.append(dict(cand))
    return survivors
