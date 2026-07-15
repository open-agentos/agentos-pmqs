"""stale_issue_age.py — quality/reliability lens.

Flags Issues open past a configurable age threshold with no recent activity.
Deterministic; no LLM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pmqs import config


class StaleIssueAgeTrigger:
    name = "stale_issue_age"
    lens_tags = ["quality_reliability"]

    def __init__(self, age_days: int | None = None):
        self.age_days = age_days if age_days is not None else config.STALE_ISSUE_AGE_DAYS

    @staticmethod
    def _days_since(ts: str | None) -> float:
        if not ts:
            return 0.0
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0

    def run(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for issue in state.get("issues", []):
            if issue.get("state", "open").lower() != "open":
                continue
            idle = self._days_since(issue.get("updatedAt") or issue.get("createdAt"))
            if idle >= self.age_days:
                ref = f"#{issue.get('number')}"
                hits.append(
                    {
                        "trigger": self.name,
                        "lens_tags": list(self.lens_tags),
                        "ref": ref,
                        "reason": f"open with no activity for {int(idle)}d (threshold {self.age_days}d)",
                        "title": f"Stale issue {ref} — no activity in {int(idle)}d: {issue.get('title', '')}",
                        "evidence": [
                            {"type": "issue", "ref": ref, "url": issue.get("url", "")}
                        ],
                    }
                )
        return hits
