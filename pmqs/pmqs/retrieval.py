"""retrieval.py — prior-outcome retrieval for lens passes (build-spec §10.2, Wave 2 #8).

    select_prior_outcomes(product_id, lens, topic, token_budget) -> [Outcome]

The ledger grows monotonically and is now Product-wide (Wave 2 item 5), so it is exactly
the thing you must not hand to an LLM whole. §10.2: "Do not dump the ledger into the
prompt." This module is the bouncer on that door.

Two rules do the real work:

1. POLICIES BYPASS RANKING. A standing rule that only applies when it scores well is not
   a standing rule. Policies are injected first and are the last thing dropped, mirroring
   the context-feed's policies-first truncation.

2. CAP BY TOKEN BUDGET, NOT ROW COUNT. A row cap looks like a bound and isn't: 20 rows of
   one-line policies and 20 rows of 5,000-word documents are the same number and wildly
   different prompts. The ledger only grows, so a row cap silently becomes a cost and
   quality failure as the product succeeds.

DEVIATION FROM §10.2, flagged (§0): the signature names `topic`, but the stated ranking
formula is "lens affinity x recency decay x type weight" -- topic appears nowhere in it.
Read literally, `topic` would be an unused parameter. Taken as: affinity means
"relevance to this pass", of which the lens tag and the topic wording are both evidence.
So `_affinity()` combines them and the formula stays three factors. If the intent was
that topic drives a separate retrieval stage, this is the wrong call and should be said
so in review.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import repository
from pmqs.outcomes.types import context_text

log = logging.getLogger(__name__)

# Roughly 4 chars per token. Deliberately an estimate: the exact count is model-specific
# and a tokenizer round-trip per outcome per lens pass costs more than the slack is worth.
# Errs high (undercounts long words), so the budget is a ceiling in practice.
_CHARS_PER_TOKEN = 4

# Half-life in days for recency decay. A decision from last week should outrank an
# equally-relevant one from two years ago, but never to the point of erasing it -- decay,
# not a cutoff, so an old decision still surfaces when nothing newer competes.
_RECENCY_HALF_LIFE_DAYS = 90.0

# Type weight: how much a prior outcome of this type informs a NEW question.
# `policy` is absent on purpose -- policies never reach the ranker.
_TYPE_WEIGHT = {
    "document": 1.0,   # briefs and analyses: the most reusable prior thinking
    "issue": 0.8,      # a concrete commitment already made
    "meeting": 0.6,    # an agenda: says what was discussed, not what was decided
    "question": 0.5,   # recorded but not resolved -- weakest evidence of a decision
}
_DEFAULT_TYPE_WEIGHT = 0.5

# Affinity when the lens doesn't match and the topic doesn't overlap. Non-zero on
# purpose: a low score is "deprioritised", not "invisible". Zero would make budget
# headroom unusable and quietly hide cross-lens precedent, which is often the most
# useful kind -- a unit_economics decision constraining a roadmap_tradeoff question.
_AFFINITY_FLOOR = 0.3

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "we", "our", "us", "should", "do", "does",
    "is", "are", "was", "were", "be", "to", "of", "in", "on", "for", "with", "at", "by",
    "it", "this", "that", "how", "what", "why", "can", "will", "would", "could",
}


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS and len(w) > 2}


def estimate_tokens(text: str) -> int:
    """Approximate token count for budgeting. See _CHARS_PER_TOKEN."""
    return max(1, len(text or "") // _CHARS_PER_TOKEN)


def _outcome_lens_tags(db: OrmSession, outcome: Any) -> list[str]:
    """The lenses an outcome came from, via its room's originating question.

    Outcomes carry no lens of their own -- the chain is outcome -> session -> question ->
    lens_tags. Returns [] for outcomes with no room or no originating question, which is
    a real and common case (a policy recorded directly), not an error.
    """
    if not outcome.session_id:
        return []
    session = repository.get_session_row(db, outcome.session_id)
    if session is None or not session.question_id:
        return []
    question = repository.get_question(db, session.question_id)
    return question.lens_tags_list if question is not None else []


def _affinity(db: OrmSession, outcome: Any, lens: str | None, topic: str | None, text: str) -> float:
    """Relevance of a prior outcome to this pass, in [_AFFINITY_FLOOR, 1.0].

    Lens match is the strong signal; topic word-overlap is the weak one. See the module
    docstring for why topic participates here at all.
    """
    score = _AFFINITY_FLOOR
    if lens and lens in _outcome_lens_tags(db, outcome):
        score = 1.0
    if topic:
        topic_words = _words(topic)
        if topic_words:
            overlap = len(topic_words & _words(text)) / len(topic_words)
            # Overlap tops out at the lens-match score rather than exceeding it: wording
            # is weaker evidence than an explicit lens tag.
            score = max(score, min(1.0, _AFFINITY_FLOOR + overlap))
    return score


def _recency_decay(created_at: str | None, now: datetime) -> float:
    """0.5 ** (age_days / half_life). Unparseable/missing timestamps decay fully to the
    floor rather than raising -- a bad timestamp shouldn't take a lens pass down."""
    if not created_at:
        return 0.5
    try:
        ts = datetime.fromisoformat(created_at)
    except ValueError:
        return 0.5
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)


def select_prior_outcomes(
    db: OrmSession,
    *,
    product_id: str | None,
    lens: str | None = None,
    topic: str | None = None,
    token_budget: int = 1000,
    member_id: str | None = None,
    now: datetime | None = None,
) -> list[Any]:
    """Prior outcomes from this Product worth showing a lens pass, best first.

    Filtered to `retired_at IS NULL` and to what `member_id` may see per §4 (reusing
    list_ledger_outcomes so visibility has exactly one implementation). Policies come
    first, unranked; everything else is ranked by affinity x recency x type weight. The
    result is capped by `token_budget`, not by row count.

    Returns [] rather than raising if anything goes wrong: this feeds prompts, and an
    un-augmented prompt is a worse answer, while an exception is no answer at all.
    """
    try:
        now = now or datetime.now(timezone.utc)
        candidates = [
            o
            for o in repository.list_ledger_outcomes(
                db, product_id=product_id, member_id=member_id
            )
            if o.retired_at is None
        ]
        if not candidates:
            return []

        policies, others = [], []
        for o in candidates:
            (policies if o.type == "policy" else others).append(o)

        scored = []
        for o in others:
            text = context_text(o.type, repository.outcome_payload(o)) or ""
            if not text.strip():
                # Nothing to put in a prompt. Issues carry their text in payload titles;
                # context_text returns "" for them, so they're skipped here rather than
                # burning budget on an empty string.
                continue
            score = (
                _affinity(db, o, lens, topic, text)
                * _recency_decay(o.created_at, now)
                * _TYPE_WEIGHT.get(o.type, _DEFAULT_TYPE_WEIGHT)
            )
            scored.append((score, o, text))
        scored.sort(key=lambda t: (-t[0], t[1].created_at or ""))

        selected: list[Any] = []
        spent = 0
        # Policies first and newest-first, so if the budget runs out mid-policy the rule
        # that survives is the current one.
        for o in sorted(policies, key=lambda x: x.created_at or "", reverse=True):
            cost = estimate_tokens(context_text("policy", repository.outcome_payload(o)))
            if spent + cost > token_budget:
                continue  # keep trying: a later, shorter policy may still fit
            selected.append(o)
            spent += cost
        for score, o, text in scored:
            cost = estimate_tokens(text)
            if spent + cost > token_budget:
                continue
            selected.append(o)
            spent += cost
        return selected
    except Exception as exc:
        log.warning("prior-outcome retrieval failed, returning none: %s", exc)
        return []
