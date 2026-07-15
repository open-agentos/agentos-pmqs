"""repository.py — basic CRUD for Questions/Outcomes (Phase 0.5 task 4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from pmqs.models import Outcome, Question, Session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Questions ---
def create_question(
    db: OrmSession,
    *,
    title: str,
    source: str,
    description: str | None = None,
    lens_tags: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    status: str = "proposed",
    score: float | None = None,
    score_dims: dict[str, Any] | None = None,
) -> Question:
    q = Question(
        title=title,
        source=source,
        description=description,
        lens_tags=json.dumps(lens_tags or []),
        evidence=json.dumps(evidence or []),
        status=status,
        score=score,
        score_dims=json.dumps(score_dims) if score_dims is not None else None,
    )
    db.add(q)
    db.commit()
    return q


def get_question(db: OrmSession, qid: str) -> Question | None:
    return db.get(Question, qid)


def list_questions(db: OrmSession, *, lens_tag: str | None = None) -> list[Question]:
    rows = list(db.scalars(select(Question)))
    if lens_tag:
        rows = [q for q in rows if lens_tag in q.lens_tags_list]
    # Ranked by score desc; unscored (None) sort last.
    rows.sort(key=lambda q: (q.score is None, -(q.score or 0.0)))
    return rows


def update_question_status(db: OrmSession, qid: str, status: str) -> Question | None:
    q = db.get(Question, qid)
    if q is None:
        return None
    q.status = status
    q.updated_at = _now()
    db.commit()
    return q


def set_question_score(db: OrmSession, qid: str, score: float, dims: dict[str, Any]) -> Question | None:
    q = db.get(Question, qid)
    if q is None:
        return None
    q.score = score
    q.score_dims = json.dumps(dims)
    q.updated_at = _now()
    db.commit()
    return q


# --- Outcomes ---
def create_outcome(
    db: OrmSession,
    *,
    type: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    github_ref: str | None = None,
) -> Outcome:
    # Policies must never sync to GitHub (product-design.md). Enforce here.
    if type == "policy" and github_ref is not None:
        raise ValueError("Policy outcomes must never carry a github_ref")
    o = Outcome(
        type=type,
        payload=json.dumps(payload),
        session_id=session_id,
        github_ref=github_ref,
    )
    db.add(o)
    db.commit()
    return o


def list_outcomes(db: OrmSession) -> list[Outcome]:
    return list(db.scalars(select(Outcome)))
