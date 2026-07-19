"""test_ci_workflow.py — guard the test gate itself (closes the #79 gap for good).

Until this workflow existed, "all checks passed" never meant the suite ran. This test
fails loudly if the Tests workflow is deleted or stops running pytest on pull requests,
so the gate can't silently regress the way it was missing before.
"""
from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tests.yml"


def _load():
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # YAML parses the bare key `on:` as boolean True; accept either spelling.
    triggers = data.get("on", data.get(True))
    return data, triggers


def test_workflow_file_exists():
    assert _WORKFLOW.is_file(), "the Tests workflow must exist (#79)"


def test_runs_on_push_and_pull_request():
    _, triggers = _load()
    assert "pull_request" in triggers
    assert "push" in triggers


def test_actually_runs_pytest():
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "pytest" in text, "the workflow must run pytest, not just lint/build"


def test_runs_offline():
    # No real model calls in CI — the run must force LLM off.
    data, _ = _load()
    env = data["jobs"]["pytest"].get("env", {})
    assert env.get("PMQS_LLM_MODE") == "off"
