"""lenses.py — session-scoped 8-lens interpretive triager (Phase 2 task 2).

The full interpretive lens pass for a war-room session. An LLM triages which of the 8
lenses are relevant to the session topic (judgment call, not a hardcoded mapping), then
produces candidate Questions per relevant lens. The batch is deduped and scored via the
EXISTING Phase 1 machinery (dedup.dedup, scoring.score_question) — not a parallel system.

COST: this is the single most expensive action in the product. It runs ONLY on the
explicit "Run lenses" action (never auto-on-open). Uses the Settings model (Haiku
default). Any LLM failure degrades to producing no candidates rather than crashing.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import context_feed, llm, repository, scoring, settings
from pmqs.config import LENS_WEIGHTS
from pmqs.dedup import dedup

log = logging.getLogger(__name__)

_LENSES = list(LENS_WEIGHTS.keys())

_TRIAGE_SYSTEM = (
    "You triage which product-analysis lenses are relevant to a decision topic. "
    f"Available lenses: {', '.join(_LENSES)}. "
    "Pick only the lenses that genuinely apply to the topic and evidence — not all of "
    'them. Respond as JSON: {"lenses": ["lens_a", "lens_b"]}. No markdown.'
)

_GEN_SYSTEM = (
    "You generate ONE sharp product-manager question for a given analysis lens and "
    "decision topic, grounded in the provided evidence. The question should be a "
    "decision the PM must make, viewed through that lens. Respond as JSON: "
    '{"title": "...", "description": "..."}. No markdown.'
)


def _topic_and_evidence(db: OrmSession, session: Any) -> tuple[str, list[dict]]:
    topic = session.topic or ""
    evidence: list[dict] = []
    if session.question_id:
        q = repository.get_question(db, session.question_id)
        if q is not None:
            topic = topic or q.title
            evidence = q.evidence_list
    return topic, evidence


def _triage_lenses(topic: str, evidence: list[dict], cfg: dict, context_block: str = "") -> list[str]:
    try:
        user = context_feed.augment(f"Topic: {topic}\nEvidence: {evidence}", context_block)
        result = llm.complete_json(_TRIAGE_SYSTEM, user, settings_cfg=cfg, max_tokens=200)
        lenses = [l for l in result.get("lenses", []) if l in _LENSES]
        return lenses or []
    except Exception as exc:
        log.warning("lens triage failed: %s", exc)
        return []


def _gen_for_lens(lens: str, topic: str, evidence: list[dict], cfg: dict, context_block: str = "") -> dict | None:
    try:
        user = context_feed.augment(
            f"Lens: {lens}\nTopic: {topic}\nEvidence: {evidence}", context_block
        )
        result = llm.complete_json(_GEN_SYSTEM, user, settings_cfg=cfg, max_tokens=350)
        if result.get("title"):
            return {
                "title": str(result["title"])[:200],
                "description": str(result.get("description", "")),
                "lens_tags": [lens],
                "evidence": evidence,
                "source": "system",
            }
    except Exception as exc:
        log.warning("lens generation failed for %s: %s", lens, exc)
    return None


def run_session_lenses(db: OrmSession, session: Any) -> list:
    """Run the explicit 8-lens pass for a session. Returns persisted proposed Questions.

    Never raises for LLM issues — returns [] if the LLM is unavailable.
    """
    if not llm.is_enabled():
        return []
    cfg = settings.get_llm(db)
    topic, evidence = _topic_and_evidence(db, session)
    if not topic:
        return []

    # Phase 3: build the unified context-feed once; feed it into triage + generation.
    # Product-scoped (build-spec §5): this session's product, so a colleague's standing
    # policies shape the lens pass but another product's never do.
    context_block = context_feed.build_context_block(db, product_id=session.product_id)

    relevant = _triage_lenses(topic, evidence, cfg, context_block)
    candidates = [
        c for c in (_gen_for_lens(l, topic, evidence, cfg, context_block) for l in relevant) if c
    ]
    if not candidates:
        return []

    deduped = dedup(candidates)
    questions = []
    for cand in deduped:
        q = repository.create_question(
            db,
            title=cand["title"],
            description=cand["description"],
            lens_tags=cand["lens_tags"],
            evidence=cand["evidence"],
            source="system",
            status="proposed",
            origin_session_id=session.id,  # B6: scope proposed questions to this session
        )
        score, dims = scoring.score_question(q)
        repository.set_question_score(db, q.id, score, dims)
        questions.append(q)
    return questions
