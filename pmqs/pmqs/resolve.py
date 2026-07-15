"""resolve.py — shared helper: turn a Phase-0 live-read pseudo-id into a real Question.

The Inbox can render live GitHub issues as cards with pseudo-ids 'issue:<n>' before any
pipeline run. Acting on such a card (open war-room, set status) requires a real persisted
Question. This resolver persists the raw issue on demand (cheap, no LLM) and returns the
Question id. Used by both the inbox status route and the workspace-open route.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession

from pmqs import repository
from pmqs.agentos_client import AgentOSClient


def resolve_question_id(db: OrmSession, qid: str) -> str | None:
    """Return a real Question id for `qid`.

    - If `qid` is a normal id, return it if the row exists, else None.
    - If `qid` is a pseudo-id 'issue:<n>', fetch that issue and persist it as a Question,
      returning the new id. Returns None if the issue can't be found.
    """
    if not qid:
        return None
    if not qid.startswith("issue:"):
        return qid if repository.get_question(db, qid) is not None else None

    number = qid.split(":", 1)[1]
    try:
        state = AgentOSClient().get_state()
        issue = next((i for i in state.get("issues", []) if str(i.get("number")) == number), None)
    except Exception:
        issue = None
    if issue is None:
        return None
    ref = f"#{issue.get('number')}"
    q = repository.create_question(
        db,
        title=issue.get("title", ""),
        source="system",
        description=issue.get("body") or "",
        evidence=[{"type": "issue", "ref": ref, "url": issue.get("url", "")}],
        status="proposed",
    )
    return q.id
