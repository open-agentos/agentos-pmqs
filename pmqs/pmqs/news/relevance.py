"""news/relevance.py — interpretive news-relevance pass (Phase 4).

The INTERPRETIVE trigger type (product-design.md): unlike deterministic repo triggers,
news relevance is an LLM judgment. ONE batched LLM call scores all unprocessed raw items
against the product profile (+ the unified context-feed), returns the relevant subset
with a per-item relevance score and a hedged, cited framing. Items scoring >= the
Settings threshold, top-N of them, become Questions (source='news', status='proposed').

Cost discipline (product owner): batched (one call), top-N cap + relevance threshold. If
nothing clears the bar, promote nothing (caller shows "nothing relevant today").

News evidence is attributed-but-hedged: {source} — "{title}" ({date}), via {url}, and the
framing language hedges ("reportedly", "according to {source}"). Reuses the existing
dedup + scoring machinery. Degrades gracefully: LLM unavailable → promote nothing, mark
nothing, no crash.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as OrmSession

from pmqs import context_feed, llm, products, repository, scoring, settings
from pmqs.config import LENS_WEIGHTS
from pmqs.dedup import dedup

log = logging.getLogger(__name__)

_LENS_KEYS = list(LENS_WEIGHTS.keys())
_DEFAULT_LENS = "competitive_positioning"

_SYSTEM = (
    "You are a product-manager's news analyst. Given a PRODUCT PROFILE and a batch of raw "
    "news items, decide which items are genuinely relevant to this product's strategy and "
    "would prompt a real PM decision. For each RELEVANT item, write a provocative, "
    "decision-oriented QUESTION (title) the PM should consider, and a short DESCRIPTION "
    "that explains why it matters — hedged and attributed (use 'reportedly' / 'according "
    "to {source}', never state second-hand news as fact). Also pick the single most "
    f"fitting LENS from: {', '.join(_LENS_KEYS)}. Score each item's relevance 0.0-1.0. "
    "Ignore irrelevant items. Respond as JSON: "
    '{"items": [{"index": <int>, "relevance": <float>, "lens": "<lens>", "title": "...", '
    '"description": "..."}]}. No markdown.'
)


def _citation(item: Any) -> dict[str, Any]:
    """Attributed-but-hedged news evidence pointer."""
    return {
        "type": "news",
        "source": item.source_label or "",
        "title": item.title or "",
        "url": item.url or "",
        "date": item.published_at or "",
        "hedged": True,
    }


_CHUNK = 25          # items judged per LLM call (a 100+ item batch in one call truncates)
_MAX_JUDGE = 200     # per product per run; the rest wait for the next Refresh


@dataclass
class NewsDiag:
    """Why the relevance pass produced what it did — enough to tell a legitimate
    "nothing relevant" apart from a broken LLM call or a product with no profile to
    judge against. Aggregated across products for one Refresh."""

    judged: int = 0                       # raw items actually scored (0 if all calls failed)
    promoted: int = 0
    top_relevance: float | None = None    # highest score seen, even below the bar
    llm_error: str = ""                   # first chunk error, if any
    products_with_items: int = 0
    products_missing_profile: int = 0     # of those with items, how many had no profile


def promote_relevant_reported(db: OrmSession, config: dict[str, Any] | None = None) -> tuple[list, NewsDiag]:
    """promote_relevant + a NewsDiag explaining the outcome. This is what the Inbox
    Refresh uses so its banner can say WHY zero, instead of a flat "nothing relevant"
    that also hides LLM failures and missing profiles."""
    diag = NewsDiag()
    if not llm.is_enabled():
        return [], diag
    cfg = config or settings.get_news_config(db)
    promoted: list = []
    for product in products.list_products(db):
        qs, pd = _promote_for_product(db, product, cfg)
        promoted.extend(qs)
        if pd["had_items"]:
            diag.products_with_items += 1
            if pd["profile_missing"]:
                diag.products_missing_profile += 1
        diag.judged += pd["judged"]
        if pd["top"] is not None:
            diag.top_relevance = pd["top"] if diag.top_relevance is None else max(diag.top_relevance, pd["top"])
        if pd["llm_error"] and not diag.llm_error:
            diag.llm_error = pd["llm_error"]
    diag.promoted = len(promoted)
    return promoted, diag


def promote_relevant(db: OrmSession, config: dict[str, Any] | None = None) -> list:
    """Run the relevance pass, once per Product, over that product's unprocessed items.

    Returns every promoted Question across all products (may be empty). Never raises
    for LLM issues.

    Before #96 this batched EVERY product's items into ONE prompt, judged them against
    ONE global profile, and created Questions with no product_id at all -- which meant
    a news question could land in the wrong product's inbox. It now loops.
    """
    return promote_relevant_reported(db, config)[0]


def _promote_for_product(db: OrmSession, product, cfg: dict[str, Any]) -> tuple[list, dict[str, Any]]:
    """One relevance pass for one Product: its items, its profile, its inbox.

    Returns (questions, diag). Items are judged in chunks of _CHUNK (a single 100+ item
    call truncates its JSON and silently promotes nothing); only chunks that actually
    ran are marked processed, so an LLM failure leaves its items for the next Refresh.
    """
    raw_items = repository.list_news_items(db, unprocessed_only=True, product_id=product.id)
    _empty = {"had_items": False, "judged": 0, "promoted": 0, "top": None,
              "llm_error": "", "profile_missing": False}
    if not raw_items:
        return [], _empty

    product_cfg = products.get_news_config(db, product)
    raw_profile = product_cfg.get("product_profile")
    profile = raw_profile or "(no product profile configured)"
    profile_missing = not (raw_profile or "").strip()
    top_n = cfg.get("top_n", 3)
    threshold = cfg.get("min_relevance", 0.5)

    context = context_feed.build_context_block(db, product_id=product.id)
    to_judge = raw_items[:_MAX_JUDGE]

    judged_items: list = []   # items from chunks that actually ran -> mark processed
    scored: list = []         # (rel, item, entry) at or above threshold
    top_seen: float | None = None
    llm_error = ""

    # Judge in chunks: one 100+ item call overflows max_tokens and returns truncated
    # JSON, which json.loads rejects -> the whole batch silently promotes nothing.
    for start in range(0, len(to_judge), _CHUNK):
        chunk = to_judge[start:start + _CHUNK]
        lines = [
            f"[{i}] source={it.source_label} | title={it.title} | summary={(it.summary or '')[:300]}"
            for i, it in enumerate(chunk)
        ]
        user = context_feed.augment(
            f"PRODUCT PROFILE:\n{profile}\n\nRAW NEWS ITEMS:\n" + "\n".join(lines), context
        )
        try:
            result = llm.complete_json(_SYSTEM, user, settings_cfg=settings.get_llm(db), max_tokens=1500)
        except Exception as exc:  # this chunk failed — leave its items unprocessed for a retry
            log.warning("news relevance pass failed for %s: %s", product.full_name, exc)
            llm_error = llm_error or str(exc)
            continue
        judged_items.extend(chunk)
        for entry in (result.get("items", []) if isinstance(result, dict) else []):
            try:
                idx = int(entry.get("index"))
                rel = float(entry.get("relevance", 0.0))
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx >= len(chunk):
                continue
            top_seen = rel if top_seen is None else max(top_seen, rel)
            if rel < threshold or not entry.get("title"):
                continue
            scored.append((rel, chunk[idx], entry))

    # Highest relevance first, cap at top_n (per product per run).
    scored.sort(key=lambda t: t[0], reverse=True)
    scored = scored[:top_n]

    diag = {
        "had_items": True,
        "judged": len(judged_items),
        "promoted": 0,
        "top": top_seen,
        "llm_error": llm_error,
        "profile_missing": profile_missing,
    }

    # Mark only the chunks that ran (a total failure marks nothing, so a retry re-judges).
    if judged_items:
        repository.mark_news_processed(db, [it.id for it in judged_items])

    if not scored:
        return [], diag

    candidates = []
    for rel, item, entry in scored:
        # B5: use the LLM-picked lens if valid, else fall back to the default.
        lens = entry.get("lens")
        lens = lens if lens in _LENS_KEYS else _DEFAULT_LENS
        candidates.append(
            {
                "title": str(entry["title"])[:200],
                "description": str(entry.get("description", "")),
                "lens_tags": [lens],
                "evidence": [_citation(item)],
                "source": "news",
                "_relevance": rel,
            }
        )

    deduped = dedup(candidates, settings_cfg=settings.get_llm(db))
    questions = []
    for cand in deduped:
        q = repository.create_question(
            db,
            title=cand["title"],
            description=cand["description"],
            lens_tags=cand["lens_tags"],
            evidence=cand["evidence"],
            source="news",
            status="proposed",
            product_id=product.id,
        )
        score, dims = scoring.score_question(q, products.weights_for(db, product.id))
        repository.set_question_score(db, q.id, score, dims)
        questions.append(q)

    diag["promoted"] = len(questions)
    return questions, diag
