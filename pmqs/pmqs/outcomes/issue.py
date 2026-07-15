"""issue.py — Issue outcome: push a Question to a real GitHub Issue (Phase 1 task 6).

On success: writes an outcomes row (type='issue', github_ref=URL) and updates the
source Question's status='promoted'. Uses the CLI push (gh), not the full
shared-credentials/App-installation flow (out of scope for MVP).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import repository
from pmqs.agentos_client import AgentOSClient


def _question_body(question: Any) -> str:
    parts = [question.description or ""]
    ev = question.evidence_list
    if ev:
        parts.append("\n\n**Evidence**")
        for e in ev:
            ref = e.get("ref", "")
            url = e.get("url", "")
            parts.append(f"- {e.get('type', 'ref')} {ref} {url}".rstrip())
    parts.append("\n\n_Pushed from PMQs._")
    return "\n".join(parts).strip()


def push_question_to_issue(
    db: OrmSession,
    question: Any,
    *,
    client: AgentOSClient | None = None,
    labels: list[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create a real Issue, record the outcome, promote the Question.

    Returns {"outcome_id", "github_ref", "number"}.
    """
    client = client or AgentOSClient()
    created = client.create_issue(title=question.title, body=_question_body(question), labels=labels)
    github_ref = created["url"]

    outcome = repository.create_outcome(
        db,
        type="issue",
        payload={"question_id": question.id, "title": question.title, "number": created.get("number")},
        session_id=session_id,
        github_ref=github_ref,
    )
    repository.update_question_status(db, question.id, "promoted")
    return {"outcome_id": outcome.id, "github_ref": github_ref, "number": created.get("number")}
