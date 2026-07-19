"""tracker.py — where an Issue outcome gets filed (Wave 3).

A thin seam so 'Issue' stops being hardcoded to GitHub. One method, create_issue.
GitHub is the live implementation (the gh-CLI path via AgentOSClient); Jira is a
registered stub so "…or a Jira task" has a home in the code without building the
integration yet (build-spec §4.3, §7 decision 4).

DEVIATION from the plan's wording ("Product Settings"): the tracker choice is stored
account-level (settings.get_tracker) rather than per-Product, because Product has no
generic settings blob and adding one is schema the plan explicitly avoids. get_tracker
already takes product_id so per-product routing is a one-function change when a second
tracker is real. Single-tenant until Phase 5, so account-level == the PM's choice today.
"""
from __future__ import annotations

from typing import Any, Protocol

from pmqs.agentos_client import AgentOSClient


class TrackerNotConfigured(RuntimeError):
    """The selected tracker has no working integration. Caller should surface, not crash."""


class Tracker(Protocol):
    kind: str

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        ...


class GitHubTracker:
    """The live tracker: create a real GitHub Issue via the existing gh-CLI client."""

    kind = "github"

    def __init__(self, client: Any = None):
        self.client = client or AgentOSClient()

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        return self.client.create_issue(title=title, body=body, labels=labels)


class JiraTracker:
    """Registered stub. Selecting Jira routes here; it declines cleanly rather than
    pretending. Swap this body for a real Jira client when the integration lands."""

    kind = "jira"

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        raise TrackerNotConfigured(
            "Jira tracker is selected but not configured. Connect Jira, or switch the "
            "tracker back to GitHub in Settings."
        )


_REGISTRY: dict[str, type] = {"github": GitHubTracker, "jira": JiraTracker}
VALID_TRACKERS = frozenset(_REGISTRY)


def get_tracker(
    db: Any = None,
    *,
    product_id: str | None = None,  # reserved for per-product routing (see module docstring)
    client: Any = None,
    kind: str | None = None,
) -> Tracker:
    """Resolve the tracker to use. `kind` overrides; otherwise the account setting;
    otherwise GitHub. `client` is only honoured by the GitHub impl (used in tests)."""
    from pmqs import settings

    resolved = kind or (settings.get_tracker(db) if db is not None else "github")
    cls = _REGISTRY.get(resolved, GitHubTracker)
    if cls is GitHubTracker:
        return GitHubTracker(client=client)
    return cls()
