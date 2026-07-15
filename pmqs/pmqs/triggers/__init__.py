"""Structural triggers (Phase 1). Deterministic queries; no LLM inside."""
from pmqs.triggers.label_conflicts import LabelConflictsTrigger
from pmqs.triggers.stale_issue_age import StaleIssueAgeTrigger

ALL_TRIGGERS = [StaleIssueAgeTrigger, LabelConflictsTrigger]

__all__ = ["StaleIssueAgeTrigger", "LabelConflictsTrigger", "ALL_TRIGGERS"]
