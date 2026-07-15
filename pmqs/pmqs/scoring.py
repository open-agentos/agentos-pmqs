"""scoring.py — unified multi-dimensional scoring (Phase 1 task 4).

One function, one formula. Lens weight is ONE input dimension among several. No
separate code path for saved vs proposed Questions. Pure function of Question + config.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pmqs import config


def _age_days(created_at: str | None) -> float:
    if not created_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)


def score_question(question: Any, cfg_weights: dict[str, float] | None = None) -> tuple[float, dict[str, float]]:
    """Return (score, per-dimension dict). Deterministic: same inputs -> same output.

    `question` may be an ORM Question or any object exposing lens_tags_list,
    evidence_list, created_at, source. Dimensions:
      - lens_weight: max configured weight across the Question's lens tags
      - evidence: more cited evidence -> higher confidence
      - recency: newer items rank slightly higher
      - source: PM-added items get a small boost (they asked on purpose)
    """
    weights = cfg_weights or config.LENS_WEIGHTS

    lens_tags = getattr(question, "lens_tags_list", None)
    if lens_tags is None:
        lens_tags = getattr(question, "lens_tags", []) or []
    evidence = getattr(question, "evidence_list", None)
    if evidence is None:
        evidence = getattr(question, "evidence", []) or []
    source = getattr(question, "source", "system")
    created_at = getattr(question, "created_at", None)

    lens_weight = max((weights.get(t, 0.5) for t in lens_tags), default=0.5)
    evidence_dim = min(1.0, 0.3 + 0.35 * len(evidence))
    age = _age_days(created_at)
    recency_dim = 1.0 / (1.0 + age / 14.0)  # halves roughly every ~2 weeks
    source_dim = 1.0 if source == "pm" else 0.8

    dims = {
        "lens_weight": round(lens_weight, 4),
        "evidence": round(evidence_dim, 4),
        "recency": round(recency_dim, 4),
        "source": round(source_dim, 4),
    }
    # Weighted sum, normalized to ~0..1.
    coeffs = {"lens_weight": 0.45, "evidence": 0.25, "recency": 0.20, "source": 0.10}
    score = sum(dims[k] * coeffs[k] for k in dims)
    return round(score, 4), dims
