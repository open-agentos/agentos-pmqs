"""refresh.py — one Inbox Refresh that collects from every data source.

Before this, the Inbox "Refresh" button ran ONLY the structural-trigger pipeline
(repo state), and News had its own separate "Fetch news now" button buried in
Settings. This unifies them: one Refresh runs the repo pass *and* the news
ingest+promotion pass, and returns a structured report saying, per source, what it
did and — crucially — *why* it produced nothing when it produces nothing.

That "why" is the whole point. A refresh that silently yields zero questions is
indistinguishable, to the PM, from a broken button. The most common legitimate
zero-results causes are all invisible in the old UI:

  repo   : the repo is simply clean (no stale/label-conflicting issues today)
  news   : no Brave key, news disabled, empty watchlist, LLM off, or nothing
           cleared the relevance bar

Each of those is a different action for the PM, so each gets its own reason code
and a plain-English line in the banner (see web/render._refresh_report_banner).

Nothing here invents questions. If the repo is clean and the watchlist quiet, the
honest answer is "nothing to raise" — the report says so precisely instead of
looking broken.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import config, llm, products, repository, settings
from pmqs.agentos_client import AgentOSClient, AgentOSClientError
from pmqs.pipeline import generate

log = logging.getLogger(__name__)

_DETAIL_CAP = 200


def _clip(text: str) -> str:
    text = " ".join((text or "").split())  # collapse whitespace/newlines
    return text[:_DETAIL_CAP]


@dataclass
class SourceResult:
    """Outcome of one data source's contribution to a refresh.

    `code` is a stable machine token the banner maps to copy; `count` is questions
    this source added; `detail` is a short, already-safe human string (issue counts,
    a truncated error, etc.). No secrets ever go in `detail`.
    """

    code: str
    count: int = 0
    detail: str = ""


@dataclass
class RefreshReport:
    repo: SourceResult
    news: SourceResult
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.repo.count + self.news.count

    # --- URL transport (PRG: the POST redirects to GET ?refresh=<token>) ---
    def encode(self) -> str:
        payload = {
            "t": self.total,
            "r": [self.repo.code, self.repo.count, self.repo.detail],
            "n": [self.news.code, self.news.count, self.news.detail],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def decode(token: str) -> "RefreshReport | None":
        if not token:
            return None
        try:
            pad = "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(token + pad)
            data = json.loads(raw)
            r, n = data["r"], data["n"]
            return RefreshReport(
                repo=SourceResult(str(r[0]), int(r[1]), str(r[2])),
                news=SourceResult(str(n[0]), int(n[1]), str(n[2])),
            )
        except Exception:  # malformed/old token → no banner rather than a crash
            return None


# ------------------------------------------------------------------ repo source
def _refresh_repo(db: OrmSession, *, product_id: str | None, repo: str | None) -> SourceResult:
    """Structural-trigger pass against live substrate state.

    A `gh`/client failure becomes a legible `error` result (with the CLI's own
    message) instead of a 500 — the old endpoint let AgentOSClientError escape.
    """
    try:
        state = AgentOSClient(repo=repo).get_state() if repo else AgentOSClient().get_state()
    except AgentOSClientError as exc:
        log.warning("refresh: repo state read failed: %s", exc)
        return SourceResult("error", 0, _clip(str(exc)))

    generated = generate(db, state, product_id=product_id)
    n = len(generated)
    if n:
        return SourceResult("generated", n)
    # Ran fine, nothing fired — say what was scanned so a clean repo doesn't read
    # as a broken button.
    open_issues = len(state.get("issues", []) or [])
    detail = f"scanned {open_issues} open issue{'s' if open_issues != 1 else ''}; " \
             f"none stale (>{config.STALE_ISSUE_AGE_DAYS}d) or label-conflicting"
    return SourceResult("clean", 0, detail)


# ------------------------------------------------------------------ news source
def _refresh_news(db: OrmSession) -> SourceResult:
    """News ingest + relevance promotion, with a specific reason for every zero.

    Pre-conditions are checked here (not just inside ingest/promote, which swallow
    them into a silent []) so the banner can tell the PM exactly which link in the
    chain — key, watchlist, provider, relevance — stopped the flow.
    """
    from pmqs.news.fetch import ingest
    from pmqs.news.relevance import promote_relevant

    cfg = settings.get_news_config(db)
    if not cfg.get("enabled", True):
        return SourceResult("disabled")

    if not settings.resolve_brave_key(db):
        ref = cfg.get("api_key_ref") or "BRAVE_API_KEY"
        return SourceResult("no_key", 0, f"set {ref} in your environment")

    prods = products.list_products(db)
    if not prods:
        return SourceResult("no_products")

    total_queries = sum(len(settings.effective_news_queries(db, p)) for p in prods)
    if total_queries == 0:
        return SourceResult("no_watchlist")

    # Fetch first (stores new raw items; per-query failures are non-fatal inside).
    try:
        fetched = ingest(db, cfg)
    except Exception as exc:  # defensive: ingest is meant to be no-raise
        log.warning("refresh: news ingest raised: %s", exc)
        return SourceResult("error", 0, _clip(str(exc)))
    n_fetched = len(fetched)

    # Promotion is the LLM judgment pass. If no provider, items are stored but
    # unjudged — a distinct, fixable state, not "nothing relevant".
    if not llm.is_enabled():
        settings.record_news_run(db, promoted=0)
        return SourceResult(
            "fetched_llm_off", 0,
            f"fetched {n_fetched} item{'s' if n_fetched != 1 else ''}; no LLM provider to judge relevance",
        )

    # Everything the promote pass will judge = new fetches + any prior backlog.
    pending = len(repository.list_news_items(db, unprocessed_only=True))
    try:
        promoted = promote_relevant(db, cfg)
    except Exception as exc:  # defensive: promote is meant to be no-raise
        log.warning("refresh: news promote raised: %s", exc)
        settings.record_news_run(db, promoted=0)
        return SourceResult("error", 0, _clip(str(exc)))
    n_promoted = len(promoted)
    settings.record_news_run(db, promoted=n_promoted)

    if n_promoted:
        return SourceResult(
            "promoted", n_promoted,
            f"from {n_fetched} newly fetched item{'s' if n_fetched != 1 else ''}",
        )
    if pending == 0:
        return SourceResult("nothing_new", 0, "no new stories for your watchlist")
    threshold = cfg.get("min_relevance", 0.5)
    return SourceResult(
        "nothing_relevant", 0,
        f"judged {pending} item{'s' if pending != 1 else ''}; none cleared the {threshold} relevance bar",
    )


# ------------------------------------------------------------------ orchestrator
def refresh_all(db: OrmSession, *, product_id: str | None = None, repo: str | None = None) -> RefreshReport:
    """Run every data source for one Inbox Refresh and return a structured report.

    `repo`/`product_id` scope the structural pass to the product whose inbox was
    refreshed. The news pass runs across every product's own watchlist (matching
    the prior 'Fetch news now' behaviour and the fact that news questions self-stamp
    the right product_id); scoping news per-product is a noted, separate follow-up.
    """
    repo_res = _refresh_repo(db, product_id=product_id, repo=repo)
    try:
        news_res = _refresh_news(db)
    except Exception as exc:  # never let news break the whole refresh
        log.warning("refresh: news source failed hard: %s", exc)
        news_res = SourceResult("error", 0, _clip(str(exc)))
    return RefreshReport(repo=repo_res, news=news_res)
