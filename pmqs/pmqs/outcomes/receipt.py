"""receipt.py — where an outcome landed, for the war-room receipt (Wave 1).

The whole point of the receipt is to answer "where can I find it?" the moment an
outcome is committed, so a PM never has to wonder whether the thing they just made is
real or where it went. Every outcome resolves to a location:

  - issue    -> the tracker URL (GitHub today), the authoritative external home
  - others   -> the Outcomes ledger, which is the durable "where" for hosted-store
               outcomes (policy/document/meeting/question)

Pure function, no DB, no I/O — it just maps (type, ids) to a link. Keeping it here
rather than inline in the API route means the client receipt, the ledger, and any
future surface all agree on one definition of "location".
"""
from __future__ import annotations

from typing import Any

# Human labels for the receipt link, per destination kind.
_LEDGER_LABEL = "Open in Outcomes"
_GITHUB_LABEL = "View on GitHub"


def location_for(
    outcome_type: str,
    *,
    github_ref: str | None = None,
    prefix: str = "",
) -> dict[str, Any]:
    """Resolve a committed outcome's location.

    `prefix` is '' for the legacy unprefixed mount or '/w/{slug}' for a workspace-scoped
    page (mirrors render.py's live-wiring prefix), so the ledger link stays inside the
    product being viewed.

    Returns {kind, url, label}. `kind` lets the client choose an affordance (open a URL
    vs. route within the app); `url` is always populated so the receipt can always link
    somewhere, even if only back to the ledger.
    """
    if outcome_type == "issue" and github_ref:
        return {"kind": "github", "url": github_ref, "label": _GITHUB_LABEL}
    # Hosted-store types (and an issue whose push somehow has no ref) resolve to the
    # ledger — the durable record every outcome lands in.
    return {"kind": "ledger", "url": f"{prefix}/outcomes", "label": _LEDGER_LABEL}


def display_title(outcome_type: str, payload: dict[str, Any]) -> str:
    """The one-line label for the receipt/ledger. Policy is free-form text, so its
    'title' is the text itself (trimmed); everything else carries a real title."""
    if outcome_type == "policy":
        text = (payload.get("text") or "").strip()
        return text if len(text) <= 80 else text[:77] + "…"
    return (payload.get("title") or payload.get("text") or "").strip()
