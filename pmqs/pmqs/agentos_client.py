"""agentos_client.py — thin wrapper for reading AgentOS substrate state.

SPEC DEVIATION (see README): the spec assumes `agentos state --json`. The installed
CLI has no such subcommand, so Phase 0 reads Issues/Labels via the `gh` CLI. The
public surface (`get_state`) is transport-agnostic so a future real `agentos state
--json` only changes `_fetch_raw`. Kept dumb: no retries/caching.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from pmqs import config


class AgentOSClientError(RuntimeError):
    pass


class AgentOSClient:
    def __init__(self, repo: str | None = None):
        self.repo = repo or config.AGENTOS_REPO

    # --- transport (swap this for `agentos state --json` if it ever ships) ---
    def _gh_json(self, args: list[str]) -> Any:
        cmd = ["gh", *args, "--repo", self.repo]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except FileNotFoundError as exc:
            raise AgentOSClientError("`gh` CLI not found on PATH") from exc
        except subprocess.CalledProcessError as exc:
            raise AgentOSClientError(
                f"gh command failed ({' '.join(cmd)}): {exc.stderr.strip()}"
            ) from exc
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AgentOSClientError(f"Could not parse gh JSON output: {exc}") from exc

    def _fetch_raw(self) -> dict[str, Any]:
        """Fetch raw substrate state. Returns {'issues': [...], 'labels': [...]}."""
        issues = self._gh_json(
            [
                "issue", "list", "--state", "open", "--limit", "100",
                "--json",
                "number,title,body,url,labels,createdAt,updatedAt,author,state",
            ]
        )
        labels = self._gh_json(["label", "list", "--limit", "200", "--json", "name,color,description"])
        return {"issues": issues, "labels": labels}

    def get_state(self) -> dict[str, Any]:
        """Return parsed substrate state as plain Python dicts.

        Shape: {"issues": [ {number,title,body,url,labels:[{name,...}],
        createdAt,updatedAt,author:{login},state}, ... ], "labels": [...]}.
        """
        return self._fetch_raw()

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        """Create a real GitHub Issue (Phase 1 outcome). Returns {number, url}."""
        cmd = ["gh", "issue", "create", "--repo", self.repo, "--title", title, "--body", body]
        for lbl in labels or []:
            cmd += ["--label", lbl]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise AgentOSClientError(f"gh issue create failed: {exc.stderr.strip()}") from exc
        url = proc.stdout.strip().splitlines()[-1].strip()
        number = None
        if "/issues/" in url:
            try:
                number = int(url.rsplit("/", 1)[-1])
            except ValueError:
                number = None
        return {"url": url, "number": number}


def get_state(repo: str | None = None) -> dict[str, Any]:
    """Module-level convenience matching the spec's `get_state()` acceptance test."""
    return AgentOSClient(repo).get_state()
