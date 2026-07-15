"""dedup.py — LLM dedup/collision pass (Phase 1 task 3). STUBBED.

LLM judgment call: given the day's batch of candidate Questions, identify pairs/groups
about the same underlying thing and merge them (merge reasoning -> surviving
Question's description).

Phase 1 status: STUBBED. No LLM call. A deterministic heuristic stands in so the
pipeline and its acceptance test run: candidates whose titles are highly similar (token
Jaccard over a threshold) or that share an evidence ref are treated as duplicates. A
real LiteLLM judgment call slots into `_llm_are_duplicates` later.
"""
from __future__ import annotations

import re
from typing import Any

_SIM_THRESHOLD = 0.6


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
    """Real LLM judgment goes here. Returns None while stubbed (fall back to heuristic)."""
    return None  # STUB


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
