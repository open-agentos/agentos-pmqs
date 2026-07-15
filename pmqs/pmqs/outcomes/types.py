"""outcomes/types.py — per-type payload builders/validators (Phase 3).

Payloads stay deliberately simple (free-form text bodies) per product-design.md:
Policy is "similar to Memory", not a structured rule schema. These are pure functions
returning the JSON-serializable payload dict for each non-Issue outcome type.

Hard rule reasserted here: nothing in this module produces or references a github_ref.
Durable outcomes are hosted-store only; policies must NEVER reach GitHub.
"""
from __future__ import annotations

from typing import Any

VALID_TYPES = {"issue", "policy", "document", "meeting", "question"}
# Types whose content is durable context that feeds agents (the unified context-feed).
DURABLE_TYPES = {"policy", "document", "meeting"}


class OutcomeValidationError(ValueError):
    pass


def build_policy(text: str) -> dict[str, Any]:
    """A standing rule — free-form text, similar to agent 'Memory'. Global scope."""
    text = (text or "").strip()
    if not text:
        raise OutcomeValidationError("policy requires non-empty text")
    return {"text": text}


def build_document(title: str, body: str = "") -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise OutcomeValidationError("document requires a title")
    return {"title": title, "body": (body or "").strip()}


def build_meeting(title: str, agenda: str = "", calendar_link: str = "") -> dict[str, Any]:
    """Meeting with an agenda. calendar_link is an optional plain string — no calendar
    integration is a dependency (product-design.md)."""
    title = (title or "").strip()
    if not title:
        raise OutcomeValidationError("meeting requires a title")
    return {
        "title": title,
        "agenda": (agenda or "").strip(),
        "calendar_link": (calendar_link or "").strip(),
    }


def build_question(title: str, body: str = "") -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise OutcomeValidationError("question requires a title")
    return {"title": title, "body": (body or "").strip()}


def context_text(outcome_type: str, payload: dict[str, Any]) -> str:
    """Render a durable outcome's payload into the text used by the context-feed."""
    if outcome_type == "policy":
        return payload.get("text", "")
    if outcome_type == "document":
        title = payload.get("title", "")
        body = payload.get("body", "")
        return f"{title}\n{body}".strip()
    if outcome_type == "meeting":
        title = payload.get("title", "")
        agenda = payload.get("agenda", "")
        return f"{title}\n{agenda}".strip()
    return ""
