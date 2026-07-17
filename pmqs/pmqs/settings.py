"""settings.py — persistent Settings store (Phase 2).

Key/value table (JSON values). First section: LLM provider/model/api-key reference.
Built to extend later (lens weights, thresholds, etc.).

Security: API keys are NOT stored raw in the DB by default. The primary path stores a
reference to an env var name (consistent with the Hermes credential pattern). A raw key
may be entered, but render_settings must never echo it back — see web/render.py.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs.models import Setting

_LLM_KEY = "llm"

# Default: Anthropic Haiku (product owner decision, 2026-07-13).
_LLM_DEFAULTS: dict[str, Any] = {
    "provider": "anthropic",
    "model": "anthropic/claude-haiku-4-5-20251001",
    "api_key_ref": "ANTHROPIC_API_KEY",  # env var name; not the key itself
    "api_key_raw": "",                     # optional inline key (kept out of renders)
    "base_url": "",
}

_CONTEXT_KEY = "context_feed"
# Phase 3: char cap for the assembled durable-outcome context block (product owner: ~4000).
_CONTEXT_DEFAULTS: dict[str, Any] = {
    "char_budget": 4000,
}

_NEWS_KEY = "news"
# Phase 4: Brave Search news config. api_key handled like the LLM key (ref preferred,
# raw masked and never rendered). Ingestion is manual-only for now.
#
# Account-wide, NOT per-product (product owner's call, #92). Product.lens_weights and
# the build-spec both say the watchlist belongs on Product, but the relevance pass is
# still product-blind (#78) -- scoping the settings while the pipeline ignores the scope
# would build a UI that lies. Both move together when #78 lands.
_NEWS_DEFAULTS: dict[str, Any] = {
    "api_key_ref": "BRAVE_API_KEY",   # env var name; not the key itself
    "api_key_raw": "",                 # optional inline key (kept out of renders)
    "enabled": True,                    # off => ingest() is a no-op, key or no key
    "watchlist": {},                    # {industry|keywords|companies|products|sources: [str]}
    "queries": [],                      # raw Brave query strings; the escape hatch
    "product_profile": "",              # free-text: what the product is / competitors / concerns
    "count": 10,                        # results requested per query (was hardcoded in fetch.py)
    "freshness": "pw",                  # Brave freshness window: pd | pw | pm | py | "" = any
    "top_n": 3,                         # max news questions promoted per ingestion run
    "min_relevance": 0.5,               # relevance threshold [0..1]; below → not promoted
    "last_run": "",                     # ISO ts of the last ingest; "" = never run
    "last_promoted": 0,                 # questions promoted by that run
}

FRESHNESS_CHOICES = (
    ("pd", "Past day"), ("pw", "Past week"), ("pm", "Past month"),
    ("py", "Past year"), ("", "Any time"),
)


def _get(db: OrmSession, key: str) -> dict[str, Any] | None:
    row = db.get(Setting, key)
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return None


def _set(db: OrmSession, key: str, value: dict[str, Any]) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=json.dumps(value))
        db.add(row)
    else:
        row.value = json.dumps(value)
    db.commit()


def get_llm(db: OrmSession) -> dict[str, Any]:
    """Return the LLM settings, merged over defaults (Anthropic Haiku)."""
    stored = _get(db, _LLM_KEY) or {}
    merged = {**_LLM_DEFAULTS, **{k: v for k, v in stored.items() if v not in (None, "")}}
    return merged


def set_llm(db: OrmSession, *, provider: str, model: str,
            api_key_ref: str = "", api_key_raw: str = "", base_url: str = "") -> dict[str, Any]:
    value = {
        "provider": provider,
        "model": model,
        "api_key_ref": api_key_ref,
        "api_key_raw": api_key_raw,
        "base_url": base_url,
    }
    _set(db, _LLM_KEY, value)
    return get_llm(db)


def has_llm_override(db: OrmSession) -> bool:
    """True if the PM has explicitly saved LLM settings (vs pure defaults)."""
    return _get(db, _LLM_KEY) is not None


def get_context_budget(db: OrmSession) -> int:
    """Char cap for the assembled context-feed block (default 4000)."""
    stored = _get(db, _CONTEXT_KEY) or {}
    try:
        return int(stored.get("char_budget") or _CONTEXT_DEFAULTS["char_budget"])
    except (TypeError, ValueError):
        return _CONTEXT_DEFAULTS["char_budget"]


def set_context_budget(db: OrmSession, char_budget: int) -> None:
    _set(db, _CONTEXT_KEY, {"char_budget": int(char_budget)})


def get_news_config(db: OrmSession) -> dict[str, Any]:
    """Brave news config merged over defaults. api_key_raw is present but must NEVER be
    rendered into HTML (callers/render mask it)."""
    stored = _get(db, _NEWS_KEY) or {}
    merged = dict(_NEWS_DEFAULTS)
    for k, v in stored.items():
        if v not in (None, ""):
            merged[k] = v
    # coerce numeric types defensively
    for key in ("top_n", "count", "last_promoted"):
        try:
            merged[key] = int(merged.get(key) if merged.get(key) is not None else _NEWS_DEFAULTS[key])
        except (TypeError, ValueError):
            merged[key] = _NEWS_DEFAULTS[key]
    try:
        merged["min_relevance"] = float(merged.get("min_relevance") or _NEWS_DEFAULTS["min_relevance"])
    except (TypeError, ValueError):
        merged["min_relevance"] = _NEWS_DEFAULTS["min_relevance"]
    if not isinstance(merged.get("queries"), list):
        merged["queries"] = []
    if not isinstance(merged.get("watchlist"), dict):
        merged["watchlist"] = {}
    merged["enabled"] = bool(merged.get("enabled", True))
    return merged


def effective_news_queries(db: OrmSession, config: dict[str, Any] | None = None) -> list[str]:
    """What ingest() will actually search: the watchlist composed, then the raw escape
    hatch appended. One implementation, so the Settings preview can't drift from the run."""
    from pmqs.news.watchlist import build_queries

    cfg = config or get_news_config(db)
    return build_queries(cfg.get("watchlist") or {}, cfg.get("queries") or [])


def record_news_run(db: OrmSession, *, promoted: int) -> None:
    """Stamp the last ingest. Lives in the existing key/value row -- a run log is a
    later question, and this only has to answer 'did that button do anything?'."""
    from datetime import datetime, timezone

    cfg = _get(db, _NEWS_KEY) or {}
    cfg["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg["last_promoted"] = int(promoted)
    _set(db, _NEWS_KEY, cfg)


def set_news_config(
    db: OrmSession,
    *,
    api_key_ref: str = "BRAVE_API_KEY",
    api_key_raw: str = "",
    enabled: bool = True,
    watchlist: dict[str, list[str]] | None = None,
    queries: list[str] | None = None,
    product_profile: str = "",
    count: int = 10,
    freshness: str = "pw",
    top_n: int = 3,
    min_relevance: float = 0.5,
) -> dict[str, Any]:
    """Preserves last_run/last_promoted: saving the watchlist is not a run, and blanking
    the stamp would make the status line lie about whether the button ever worked."""
    current = _get(db, _NEWS_KEY) or {}
    value = {
        "api_key_ref": api_key_ref,
        "api_key_raw": api_key_raw,
        "enabled": bool(enabled),
        "watchlist": watchlist or {},
        "queries": queries or [],
        "product_profile": product_profile,
        "count": int(count),
        "freshness": freshness,
        "top_n": int(top_n),
        "min_relevance": float(min_relevance),
        "last_run": current.get("last_run", ""),
        "last_promoted": current.get("last_promoted", 0),
    }
    _set(db, _NEWS_KEY, value)
    return get_news_config(db)


def resolve_brave_key(db: OrmSession) -> str:
    """Resolve the Brave API key: inline raw > env var named by api_key_ref (process env
    then ~/.hermes dotenv). Returns '' if unavailable. NEVER logged/rendered."""
    import os

    cfg = _get(db, _NEWS_KEY) or {}
    raw = cfg.get("api_key_raw") or ""
    if raw:
        return raw
    ref = cfg.get("api_key_ref") or _NEWS_DEFAULTS["api_key_ref"]
    if not ref:
        return ""
    val = os.environ.get(ref)
    if val:
        return val
    # fall back to ~/.hermes/.env (same store the LLM key uses)
    from pathlib import Path

    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    env_file = home / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == ref:
                return v.strip()
    return ""
