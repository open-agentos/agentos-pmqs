"""Central config. Simple env/dict — no settings UI in Phase 1 (per spec)."""
from __future__ import annotations

import os
from pathlib import Path

# Target AgentOS repo (owner/repo form for gh, or a local path).
AGENTOS_REPO = os.environ.get("PMQS_AGENTOS_REPO", "open-agentos/agentos-pmqs")

# Local checkout of the agentos-pmqs repo (used as cwd for any future `agentos` calls).
_default_repo_path = Path(__file__).resolve().parents[2]  # .../agentos-pmqs
AGENTOS_REPO_PATH = Path(os.environ.get("PMQS_AGENTOS_REPO_PATH", str(_default_repo_path)))

# SQLite DB location (Phase 0.5+).
DB_PATH = Path(os.environ.get("PMQS_DB_PATH", str(Path(__file__).resolve().parent / "pmqs.db")))

# Mockup HTML reused for rendering (Phase 0).
MOCKUP_HTML = Path(
    os.environ.get(
        "PMQS_MOCKUP_HTML",
        str(_default_repo_path / "docs" / "pmqs-mockup.html"),
    )
)

# --- Phase 1 scoring: per-lens weight defaults (config, not UI). ---
# 8-lens taxonomy from product-design.md. Weight is one dimension of the formula.
LENS_WEIGHTS: dict[str, float] = {
    "competitive_positioning": 0.6,
    "growth_adoption": 0.6,
    "unit_economics": 0.7,
    "risk_exposure": 1.0,
    "roadmap_tradeoff": 0.7,
    "quality_reliability": 0.9,
    "org_execution_drag": 0.5,
    "narrative_positioning": 0.5,
}

# Structural trigger thresholds.
STALE_ISSUE_AGE_DAYS = int(os.environ.get("PMQS_STALE_ISSUE_AGE_DAYS", "14"))

# Label conflict pairs (risk/exposure lens). Defined here, not fixed by the spec.
LABEL_CONFLICT_PAIRS: list[tuple[str, str]] = [
    ("status:blocked", "status:in-progress"),  # can't be actively worked and blocked
    ("status:done", "status:in-review"),        # can't be done and still under review
    ("status:approved", "status:changes-requested"),  # contradictory review verdicts
]
