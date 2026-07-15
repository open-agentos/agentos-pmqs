"""llm.py — LiteLLM client for PMQs framing/dedup passes.

Mirrors the 3Qs convention: default mode 'hermes' inherits whichever LLM provider the
local Hermes Agent install is configured with (no product-side API keys). Mode 'api'
reads a key from the environment.

Provider-agnostic via LiteLLM so models swap without code changes. All callers should
treat an LLM failure as recoverable — framing/dedup degrade gracefully rather than
crash the pipeline.

Config (pmqs.config / env):
  PMQS_LLM_MODE      'hermes' (default) | 'api' | 'off'
  PMQS_LLM_MODEL     override model (optional)
  PMQS_LLM_API_KEY_ENV   env var name holding the key (api mode)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_NATIVE_PROVIDERS = {"anthropic", "cohere", "google", "mistral", "together_ai"}


class LlmUnavailable(RuntimeError):
    """Raised when no LLM is configured/reachable. Callers should fall back."""


class _Resolved(NamedTuple):
    model: str
    base_url: str
    api_key: str


# ---------------------------------------------------------------- hermes mode
def _load_hermes_env(home: Path) -> dict[str, str]:
    env_file = home / ".env"
    out: dict[str, str] = {}
    if not env_file.exists():
        return out
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _resolve_credential(auth: dict, hermes_env: dict[str, str], provider: str = "") -> str:
    """Find the access token for a specific provider.

    Hermes' credential_pool is keyed by provider. We must match the configured
    provider (e.g. 'anthropic') rather than grabbing the first entry with a token —
    the first entry is often a different provider (copilot/openai) whose token would
    be rejected by the target API. Falls back to a provider-agnostic scan only if the
    provider isn't found.
    """
    pool: dict = auth.get("credential_pool", {})

    def _token_from_entries(entries) -> str:
        if not isinstance(entries, list):
            return ""
        for entry in entries:
            tok = entry.get("access_token", "")
            if tok:
                return tok
            source = entry.get("source", "")
            if source.startswith("env:"):
                var = source[4:]
                tok = os.environ.get(var) or hermes_env.get(var, "")
                if tok:
                    return tok
        return ""

    # 1. Exact provider match (preferred).
    if provider and provider in pool:
        tok = _token_from_entries(pool[provider])
        if tok:
            return tok

    # 2. Provider-agnostic fallback (only if configured provider yielded nothing).
    for _prov, entries in pool.items():
        tok = _token_from_entries(entries)
        if tok:
            return tok
    return ""


def _resolve_hermes() -> _Resolved:
    import yaml

    home = _HERMES_HOME
    config_path = home / "config.yaml"
    if not config_path.exists():
        raise LlmUnavailable(f"Hermes config not found at {config_path}; set PMQS_LLM_MODE=api or =off")

    hermes_cfg = yaml.safe_load(config_path.read_text()) or {}
    model_cfg = hermes_cfg.get("model", {})
    base_url = (model_cfg.get("base_url") or "").rstrip("/")
    model = os.environ.get("PMQS_LLM_MODEL") or model_cfg.get("default", "gpt-4o-mini")
    provider = model_cfg.get("provider", "")
    api_key = model_cfg.get("api_key", "")

    hermes_env = _load_hermes_env(home)
    auth_path = home / "auth.json"
    if not api_key and auth_path.exists():
        api_key = _resolve_credential(json.loads(auth_path.read_text()), hermes_env, provider=provider)
    if not api_key:
        raise LlmUnavailable("No usable token in Hermes credential store; run 'hermes auth' or set PMQS_LLM_MODE=api")

    if not base_url and provider in _NATIVE_PROVIDERS:
        if provider == "anthropic" and not model.startswith("anthropic/"):
            model = f"anthropic/{model}"
        elif provider != "anthropic" and "/" not in model:
            model = f"{provider}/{model}"
        return _Resolved(model=model, base_url="", api_key=api_key)

    if not base_url:
        raise LlmUnavailable("Hermes config has no base_url and no recognised native provider")
    return _Resolved(model=f"openai/{model}" if not model.startswith("openai/") else model,
                     base_url=base_url, api_key=api_key)


def _resolve_api() -> _Resolved:
    model = os.environ.get("PMQS_LLM_MODEL", "gpt-4o-mini")
    key_env = os.environ.get("PMQS_LLM_API_KEY_ENV", "OPENAI_API_KEY")
    api_key = os.environ.get(key_env, "")
    if not api_key:
        raise LlmUnavailable(f"API mode: env var {key_env} is empty")
    return _Resolved(model=model, base_url="", api_key=api_key)


def _resolve_from_settings(cfg: dict[str, Any]) -> _Resolved:
    """Build a resolved config from saved Settings (Settings > env > Hermes).

    api_key precedence: inline raw key > env var named by api_key_ref (process env,
    then ~/.hermes dotenv). Model is used as-is (assumed already provider-prefixed for
    native providers, e.g. 'anthropic/claude-...').
    """
    provider = cfg.get("provider", "")
    model = cfg.get("model") or "anthropic/claude-haiku-4-5-20251001"
    base_url = (cfg.get("base_url") or "").rstrip("/")

    api_key = cfg.get("api_key_raw") or ""
    if not api_key:
        ref = cfg.get("api_key_ref") or ""
        if ref:
            dotenv = _load_hermes_env(_HERMES_HOME)
            api_key = os.environ.get(ref) or dotenv.get(ref, "")
    if not api_key:
        raise LlmUnavailable(
            f"Settings LLM: no API key (checked inline + env '{cfg.get('api_key_ref')}')"
        )

    if base_url:
        return _Resolved(
            model=f"openai/{model}" if not model.startswith("openai/") else model,
            base_url=base_url, api_key=api_key,
        )
    # Native provider path: ensure model is provider-prefixed.
    if provider in _NATIVE_PROVIDERS and "/" not in model:
        model = f"{provider}/{model}"
    return _Resolved(model=model, base_url="", api_key=api_key)


def _resolve(settings_cfg: dict[str, Any] | None = None) -> _Resolved:
    # Settings take precedence when provided and non-empty.
    if settings_cfg:
        return _resolve_from_settings(settings_cfg)
    mode = os.environ.get("PMQS_LLM_MODE", "hermes").lower()
    if mode == "off":
        raise LlmUnavailable("PMQS_LLM_MODE=off")
    if mode == "api":
        return _resolve_api()
    return _resolve_hermes()


# ---------------------------------------------------------------- public API
def is_enabled() -> bool:
    return os.environ.get("PMQS_LLM_MODE", "hermes").lower() != "off"


def complete(system: str, user: str, *, settings_cfg: dict[str, Any] | None = None,
             temperature: float = 0.2, max_tokens: int = 800) -> str:
    """Single-shot completion. Raises LlmUnavailable if no LLM is configured/reachable.

    When `settings_cfg` is provided (from pmqs.settings.get_llm), it takes precedence
    over env/Hermes resolution. Callers must catch exceptions and fall back — LLM
    failure is never fatal to the pipeline.
    """
    resolved = _resolve(settings_cfg)
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover
        raise LlmUnavailable("litellm not installed") from exc

    kwargs: dict[str, Any] = {"model": resolved.model, "api_key": resolved.api_key}
    if resolved.base_url:
        kwargs["api_base"] = resolved.base_url

    resp = litellm.completion(
        **kwargs,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp["choices"][0]["message"]["content"].strip()


def complete_json(system: str, user: str, **kw) -> Any:
    """Completion that expects JSON back. Tolerates ```json fences."""
    raw = complete(system, user, **kw)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text)
