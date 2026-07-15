"""test_no_hazard.py — hard rule: no `agentos apply`/`upgrade` calls anywhere.

Cheap insurance against the adopt->upgrade data-loss hazard (architecture.md, #47).
"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "pmqs"

# Match a subprocess/CLI invocation of agentos apply|upgrade — not doc mentions.
FORBIDDEN = re.compile(r"""agentos["'\s,\]]+.*?(apply|upgrade)""")


def test_no_agentos_apply_or_upgrade_calls():
    offenders = []
    for py in PKG.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            # Only flag list/command constructions containing agentos + apply/upgrade
            if '"agentos"' in line or "'agentos'" in line:
                if "apply" in line or "upgrade" in line:
                    offenders.append(f"{py.name}:{i}: {stripped}")
    assert not offenders, "Forbidden agentos apply/upgrade invocation found:\n" + "\n".join(offenders)
