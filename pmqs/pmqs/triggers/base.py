"""Trigger protocol (Phase 1). Triggers are deterministic — no LLM inside."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Trigger(Protocol):
    """A structural/threshold trigger.

    `run(state)` takes raw AgentOS state ({'issues': [...], 'labels': [...]}) and
    returns a list of raw hit dicts. A hit is deterministic and LLM-free; it carries
    enough to build a Question later (via framing.frame) and cite evidence:

        {
          "trigger": "stale_issue_age",
          "lens_tags": ["quality_reliability"],
          "ref": "#42",
          "reason": "open 30d with no activity",
          "title": <optional pre-framed title>,
          "evidence": [{"type": "issue", "ref": "#42", "url": "..."}],
        }
    """

    name: str
    lens_tags: list[str]

    def run(self, state: dict[str, Any]) -> list[dict[str, Any]]: ...
