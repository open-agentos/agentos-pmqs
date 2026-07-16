"""dedup.py — LLM dedup/collision pass (Phase 1 task 3; widened in Wave 2 item 9).

LLM judgment call: given the day's batch of candidate Questions, identify pairs/groups
about the same underlying thing and merge them (merge reasoning -> surviving
Question's description).

The LLM judgment goes through pmqs.llm. If the LLM is unavailable or errors, a
deterministic heuristic stands in (token Jaccard over a threshold, or a shared
evidence ref) so the pipeline never breaks. Set PMQS_LLM_MODE=off to force heuristic.

WAVE 2 ITEM 9 (build-spec §10.3) — Loops 2 and 3.
The same judgment's EVIDENCE widens; there is deliberately no second pass (§10.3:
"Widen the existing LLM dedup judgment -- do not add a second one"). It now also weighs:
  - the Product's prior outcomes, retrieved and budgeted by retrieval.select_prior_outcomes
  - other members' open inbox items
and returns a verdict rather than a bare boolean:
  raise    -- novel; raise it (the default, and what every failure degrades to)
  suppress -- already decided; do not raise
  reframe  -- raise, framed as building on outcome N
  route    -- a colleague is already deciding this; surface their Workspace instead

TWO RULES THAT LOOK LIKE CAUTION AND ARE ACTUALLY THE PRODUCT:

1. PRIOR DECISIONS ARE POSITIONS TO TEST, NOT SETTLED FACT (§10.3, §12 groupthink).
   A candidate that ARGUES AGAINST a prior decision is the most valuable thing the lens
   pass can produce, and it is precisely what a naive "is this about the same topic?"
   check destroys -- a challenge to a policy has near-total word overlap with it. The
   prompt says so explicitly, and a test asserts a challenge survives.

2. THE FALLBACK NEVER SUPPRESSES. When the LLM is unavailable the widened judgment
   degrades to `raise`, not to a token-overlap guess. The two errors are not symmetric:
   raising a duplicate wastes a minute and is visible; suppressing a novel question is
   invisible and unrecoverable -- nobody ever learns it was suppressed. Fail open.
   (Intra-batch merging keeps its heuristic: merging two of today's candidates is a
   different, recoverable act from silencing a question against the whole ledger.)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pmqs import llm

log = logging.getLogger(__name__)

_SIM_THRESHOLD = 0.6

_VERDICTS = {"raise", "suppress", "reframe", "route"}
_DEFAULT_VERDICT = "raise"

_PRIOR_SYSTEM = (
    "You are triaging a proposed product-management question against what a product team "
    "has ALREADY decided and what colleagues are ALREADY working on.\n\n"
    "Return ONE verdict as JSON, no markdown:\n"
    '{"verdict": "raise"|"suppress"|"reframe"|"route", "prior_ref": <int|null>, '
    '"colleague_ref": <int|null>, "reason": "<one short sentence>"}\n\n'
    "  raise    - novel, or a genuine challenge to a prior decision. THE DEFAULT.\n"
    "  suppress - this exact question is already answered by a prior decision and asking "
    "it again adds nothing. Set prior_ref.\n"
    "  reframe  - worth asking, but only as a follow-on to a prior decision. Set "
    "prior_ref.\n"
    "  route    - a colleague is already deciding this exact question. Set "
    "colleague_ref.\n\n"
    "CRITICAL: prior decisions are POSITIONS TO TEST, NOT SETTLED FACT. A question that "
    "challenges, revisits, or argues against a prior decision is NOT a duplicate of it -- "
    "it is the most valuable question here. Raise it. Only suppress when the question is "
    "genuinely already answered and re-asking adds nothing new. When in doubt, raise."
)

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


def _prior_evidence(db, *, product_id, member_id, lens, topic, token_budget, now):
    """(prior outcome texts, colleague inbox items) — the widened evidence set (§10.3)."""
    from pmqs import retrieval, repository

    outcomes = retrieval.select_prior_outcomes(
        db, product_id=product_id, lens=lens, topic=topic,
        token_budget=token_budget, member_id=member_id, now=now,
    )
    from pmqs.outcomes.types import context_text

    priors = []
    for o in outcomes:
        text = context_text(o.type, repository.outcome_payload(o))
        if text.strip():
            priors.append((o, text))
    colleagues = repository.list_other_members_open_questions(
        db, product_id=product_id, member_id=member_id
    )
    return priors, colleagues


def _judge_against_prior(cand, priors, colleagues):
    """Widened judgment for one candidate. Returns (verdict, prior_outcome, colleague_q).

    Degrades to `raise` on every failure path -- see rule 2 in the module docstring.
    """
    if not llm.is_enabled() or (not priors and not colleagues):
        return _DEFAULT_VERDICT, None, None

    prior_lines = "\n".join(
        f"[{i}] ({o.type}) {text[:400]}" for i, (o, text) in enumerate(priors)
    ) or "(none)"
    colleague_lines = "\n".join(
        f"[{i}] {q.title}" for i, q in enumerate(colleagues)
    ) or "(none)"
    user = (
        f"PROPOSED QUESTION:\n  title: {cand.get('title')}\n"
        f"  description: {(cand.get('description') or '')[:400]}\n\n"
        f"PRIOR DECISIONS (positions to test, not settled fact):\n{prior_lines}\n\n"
        f"COLLEAGUES' OPEN QUESTIONS:\n{colleague_lines}"
    )
    try:
        result = llm.complete_json(_PRIOR_SYSTEM, user)
    except Exception as exc:
        log.warning("prior-awareness judgment failed, raising by default: %s", exc)
        return _DEFAULT_VERDICT, None, None
    if not isinstance(result, dict):
        return _DEFAULT_VERDICT, None, None

    verdict = result.get("verdict")
    if verdict not in _VERDICTS:
        return _DEFAULT_VERDICT, None, None

    prior = _pick(priors, result.get("prior_ref"))
    prior_outcome = prior[0] if prior else None
    colleague = _pick(colleagues, result.get("colleague_ref"))

    # A verdict that names nothing has nothing to stand on. suppress/reframe without a
    # prior decision, or route without a colleague, is the model saying "duplicate" with
    # no duplicate to point at -- fall back to raising rather than acting on it.
    if verdict in ("suppress", "reframe") and prior_outcome is None:
        return _DEFAULT_VERDICT, None, None
    if verdict == "route" and colleague is None:
        return _DEFAULT_VERDICT, None, None
    return verdict, prior_outcome, colleague


def _pick(seq, idx):
    try:
        i = int(idx)
    except (TypeError, ValueError):
        return None
    return seq[i] if 0 <= i < len(seq) else None


def judge_prior_awareness(
    candidates,
    db,
    *,
    product_id,
    member_id=None,
    lens=None,
    topic=None,
    token_budget=800,
    now=None,
):
    """Annotate candidates with a §10.3 verdict, in place, and return them.

    Adds `_verdict` to every candidate plus, where relevant, `_prior_outcome_id` and
    `_route_session_id`/`_route_question_id`. Callers decide what to do with them --
    see raisable().

    Suppressed candidates are LOGGED, not silently dropped: an invisible suppression is
    exactly the failure mode §12 warns about, and someone has to be able to find out
    the pass ate a question.
    """
    from pmqs import repository

    try:
        priors, colleagues = _prior_evidence(
            db, product_id=product_id, member_id=member_id, lens=lens,
            topic=topic, token_budget=token_budget, now=now,
        )
    except Exception as exc:
        log.warning("prior evidence assembly failed, raising all: %s", exc)
        for cand in candidates:
            cand["_verdict"] = _DEFAULT_VERDICT
        return candidates

    for cand in candidates:
        verdict, prior_outcome, colleague = _judge_against_prior(cand, priors, colleagues)

        if verdict == "route":
            session = repository.find_visible_session_for_question(
                db, question_id=colleague.id, member_id=member_id
            )
            if session is None:
                # The colleague's room is private to them. Routing there would leak both
                # its existence and its topic, so this degrades to raising (§4).
                verdict = _DEFAULT_VERDICT
            else:
                cand["_route_session_id"] = session.id
                cand["_route_question_id"] = colleague.id

        if verdict == "reframe" and prior_outcome is not None:
            cand["_prior_outcome_id"] = prior_outcome.id
            cand["description"] = (
                (cand.get("description") or "")
                + f"\n[prior] Builds on an earlier decision ({prior_outcome.type} "
                f"{prior_outcome.id}). Treat that decision as a position to test, not "
                f"as settled."
            )
        elif verdict == "suppress" and prior_outcome is not None:
            cand["_prior_outcome_id"] = prior_outcome.id
            log.info(
                "dedup suppressed candidate %r as already decided by outcome %s",
                cand.get("title"), prior_outcome.id,
            )

        cand["_verdict"] = verdict
    return candidates


def raisable(candidates):
    """The candidates that should actually become Questions.

    `suppress` is already decided; `route` points at a colleague's Workspace instead of
    raising a duplicate (§10.3). Both keep their annotations for callers that want to
    surface them.
    """
    return [c for c in candidates if c.get("_verdict", _DEFAULT_VERDICT) not in ("suppress", "route")]
