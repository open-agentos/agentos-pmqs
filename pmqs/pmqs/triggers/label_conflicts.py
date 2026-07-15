"""label_conflicts.py — risk/exposure lens.

Flags Issues carrying contradictory labels. Conflict pairs are defined in config
(LABEL_CONFLICT_PAIRS) — not fixed by the spec. Deterministic; no LLM.
"""
from __future__ import annotations

from typing import Any

from pmqs import config


class LabelConflictsTrigger:
    name = "label_conflicts"
    lens_tags = ["risk_exposure"]

    def __init__(self, conflict_pairs: list[tuple[str, str]] | None = None):
        self.conflict_pairs = conflict_pairs if conflict_pairs is not None else config.LABEL_CONFLICT_PAIRS

    def run(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for issue in state.get("issues", []):
            names = {l.get("name") for l in issue.get("labels", []) if l.get("name")}
            conflicts = [(a, b) for (a, b) in self.conflict_pairs if a in names and b in names]
            if conflicts:
                ref = f"#{issue.get('number')}"
                pairs = ", ".join(f"{a}✗{b}" for a, b in conflicts)
                hits.append(
                    {
                        "trigger": self.name,
                        "lens_tags": list(self.lens_tags),
                        "ref": ref,
                        "reason": f"contradictory labels: {pairs}",
                        "title": f"Label conflict on {ref}: {pairs}",
                        "evidence": [
                            {"type": "issue", "ref": ref, "url": issue.get("url", "")}
                        ],
                    }
                )
        return hits
