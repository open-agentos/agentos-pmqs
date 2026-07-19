"""suggest.py — recommend which outcome this session warrants (Wave 4).

Removes the "didn't know WHAT kind" confound from the front, before the PM even picks.
On an explicit wrap-up (not on every message — cost discipline, build-spec §7 decision
1), the war-room partner names the strongest outcome: a type, a short draft title, and
a one-line rationale. The PM accepts (→ draft it), picks another, or closes with a
reason. Suggestion is NEVER creation: this only proposes.

One LLM call, fail-open. With no LLM it returns a soft, non-degraded-pushy result
(type=None) so the UI simply shows "no specific suggestion — pick one below" rather
than inventing a recommendation.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import llm, settings
from pmqs.outcomes.draft import _session_context
from pmqs.outcomes.types import VALID_TYPES

log = logging.getLogger(__name__)

_SYSTEM = (
    "You advise a product manager wrapping up a war-room session on the single most "
    "useful OUTCOME to produce next, grounded strictly in the session. Outcome types: "
    "issue (code/engineering work), policy (a durable standing rule), document (a "
    "briefing/PRD/analysis), meeting (needs a room, with an agenda), question (a sharper "
    "follow-up for later). Pick the ONE that best captures what the session actually "
    "decided or surfaced. If the session reached nothing worth recording, say so. "
    "Respond as JSON with keys: type (one of issue|policy|document|meeting|question|"
    "none), title (a short draft title, empty if none), rationale (one sentence)."
)


def suggest_outcome(db: OrmSession, session: Any) -> dict[str, Any]:
    """Recommend an outcome for this session. Never raises.

    Returns {type, title, rationale, degraded}. `type` is a valid outcome type or None
    (nothing worth recording / LLM unavailable).
    """
    if not llm.is_enabled():
        return {
            "type": None,
            "title": "",
            "rationale": "Pick the outcome that fits — PMQs will draft it from this session.",
            "degraded": True,
        }

    context = _session_context(db, session)
    user = f"{context}\n\nRecommend the single best outcome as JSON."
    try:
        result = llm.complete_json(
            _SYSTEM, user, settings_cfg=settings.get_llm(db), max_tokens=300
        )
        if not isinstance(result, dict):
            raise ValueError("non-dict result")
        otype = str(result.get("type", "")).strip().lower()
        if otype not in VALID_TYPES:
            otype = None  # 'none' or anything odd → no pushy suggestion
        return {
            "type": otype,
            "title": str(result.get("title", "")).strip(),
            "rationale": str(result.get("rationale", "")).strip(),
            "degraded": False,
        }
    except Exception as exc:
        log.warning("outcome suggestion failed: %s", exc)
        return {
            "type": None,
            "title": "",
            "rationale": "Pick the outcome that fits — PMQs will draft it from this session.",
            "degraded": True,
        }
