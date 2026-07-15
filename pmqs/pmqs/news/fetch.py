"""news/fetch.py — Brave Search news fetcher + ingestion (Phase 4).

Queries the Brave Search News API for the configured terms, parses results into raw
NewsItems, and writes new ones (dedup by URL). The pure parser (`parse_brave_results`)
is unit-tested offline against a fixture; the network client is a thin wrapper.

Security: the Brave key is resolved at runtime via settings.resolve_brave_key (raw > env
> ~/.hermes dotenv). It is NEVER hardcoded, logged, or rendered.
Robustness: per-query network/HTTP failure is non-fatal (skipped + logged).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import repository, settings

log = logging.getLogger(__name__)

_BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"


def parse_brave_results(data: dict[str, Any], query: str = "") -> list[dict[str, Any]]:
    """Pure parser: Brave news JSON -> list of raw-item dicts. Skips entries w/o a URL."""
    items = []
    for r in data.get("results", []) or []:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        meta = r.get("meta_url") or {}
        items.append(
            {
                "url": url,
                "title": (r.get("title") or "").strip(),
                "summary": (r.get("description") or "").strip() or None,
                "published_at": r.get("page_age") or r.get("age"),
                "source_label": meta.get("hostname") or query,
            }
        )
    return items


def _fetch_query(query: str, api_key: str, count: int = 10) -> list[dict[str, Any]]:
    """Network call for one query. Returns parsed raw-item dicts; [] on any failure."""
    try:
        import httpx

        resp = httpx.get(
            _BRAVE_NEWS_URL,
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=20.0,
        )
        resp.raise_for_status()
        return parse_brave_results(resp.json(), query=query)
    except Exception as exc:  # network, HTTP, JSON — all non-fatal per query
        log.warning("Brave fetch failed for query %r: %s", query, exc)
        return []


def ingest(db: OrmSession, config: dict[str, Any] | None = None) -> list:
    """Fetch all configured queries, persist new raw items (dedup by URL).

    Returns the list of newly-created NewsItem rows. Never raises for fetch failures;
    returns [] if no key/queries are configured.
    """
    cfg = config or settings.get_news_config(db)
    queries = cfg.get("queries") or []
    if not queries:
        return []
    api_key = settings.resolve_brave_key(db)
    if not api_key:
        log.warning("news ingest: no Brave API key configured")
        return []

    created = []
    for q in queries:
        for raw in _fetch_query(q, api_key):
            item = repository.create_news_item(
                db,
                url=raw["url"],
                title=raw["title"],
                source_label=raw["source_label"],
                summary=raw["summary"],
                published_at=raw["published_at"],
            )
            if item is not None:  # None == dedup hit
                created.append(item)
    return created
