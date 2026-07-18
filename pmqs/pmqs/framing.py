"""framing.py — LLM framing pass (Phase 1 task 2).

Runs AFTER a structural trigger fires, as a separate step. Takes a trigger's raw hit
and produces a human-readable title/description. Decoupled from the trigger so the
trigger stays deterministic/swappable.

The LLM call goes through pmqs.llm (LiteLLM). When the caller passes settings_cfg it
resolves through saved Settings (the global provider default); otherwise it falls back
to PMQS_LLM_MODE (Hermes/env).
Critically: an LLM failure must NOT crash the trigger pipeline — the fallback below
guarantees a Question still gets a usable title/description. Set PMQS_LLM_MODE=off to
force the deterministic fallback (e.g. in tests/offline).
"""
from __future__ import annotations

import logging
from typing import Any

from pmqs import llm

log = logging.getLogger(__name__)

_SYSTEM = (
    "You frame product-management questions for a PM's decision inbox. Given a raw "
    "structural-trigger hit against a software repo, write a concise, human-readable "
    "question TITLE (<=120 chars, phrased as a decision the PM must make) and a short "
    "DESCRIPTION (2-4 sentences: what was detected, why it matters, what's at stake). "
    'Respond as JSON: {"title": "...", "description": "..."}. No markdown.'
)


def _call_llm(hit: dict[str, Any], settings_cfg: dict[str, Any] | None = None) -> dict[str, str] | None:
    """Real LLM framing via pmqs.llm. Returns None on any failure (caller falls back)."""
    if not llm.is_enabled():
        return None
    user = (
        f"Trigger: {hit.get('trigger')}\n"
        f"Lens: {', '.join(hit.get('lens_tags', []))}\n"
        f"Reference: {hit.get('ref')}\n"
        f"Reason: {hit.get('reason')}\n"
        f"Draft title (optional): {hit.get('title', '')}"
    )
    try:
        result = llm.complete_json(_SYSTEM, user, settings_cfg=settings_cfg)
        if isinstance(result, dict) and result.get("title") and result.get("description"):
            return {"title": str(result["title"])[:200], "description": str(result["description"])}
    except Exception as exc:
        log.warning("framing LLM call failed, falling back: %s", exc)
    return None


def _fallback(hit: dict[str, Any]) -> dict[str, str]:
    ref = hit.get("ref", "")
    reason = hit.get("reason", "flagged by a structural trigger")
    title = hit.get("title") or f"Review {ref}: {reason}"
    desc = (
        f"[auto-framed / LLM stub]\n"
        f"Trigger: {hit.get('trigger', 'unknown')}\n"
        f"Reason: {reason}\n"
        f"Reference: {ref}"
    )
    return {"title": title[:200], "description": desc}


def frame(hit: dict[str, Any], *, settings_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Produce {title, description} for a trigger hit. Never raises.

    When `settings_cfg` (from pmqs.settings.get_llm) is provided, the LLM is resolved
    through saved Settings — the same source the rest of the pipeline uses — so the
    global provider default applies here too rather than only to env/Hermes resolution.
    """
    try:
        result = _call_llm(hit, settings_cfg)
    except Exception:
        result = None
    if result and result.get("title") and result.get("description"):
        return result
    return _fallback(hit)
