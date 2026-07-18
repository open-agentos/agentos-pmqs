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


def promote_relevant(db: OrmSession, config: dict[str, Any] | None = None) -> list:
    """Run the relevance pass, once per Product, over that product's unprocessed items.

    Returns every promoted Question across all products (may be empty). Never raises
    for LLM issues.

    Before #96 this batched EVERY product's items into ONE prompt, judged them against
    ONE global profile, and created Questions with no product_id at all -- which meant
    a news question could land in the wrong product's inbox. It now loops.
    """
    if not llm.is_enabled():
        return []
    cfg = config or settings.get_news_config(db)
    promoted: list = []
    for product in products.list_products(db):
        promoted.extend(_promote_for_product(db, product, cfg))
    return promoted


def _promote_for_product(db: OrmSession, product, cfg: dict[str, Any]) -> list:
    """One relevance pass for one Product: its items, its profile, its inbox."""
    raw_items = repository.list_news_items(db, unprocessed_only=True, product_id=product.id)
    if not raw_items:
        return []

    product_cfg = products.get_news_config(db, product)
    profile = product_cfg.get("product_profile") or "(no product profile configured)"
    top_n = cfg.get("top_n", 3)
    threshold = cfg.get("min_relevance", 0.5)

    # Build the batched prompt: numbered items so the LLM can reference by index.
    lines = []
    for idx, it in enumerate(raw_items):
        lines.append(
            f"[{idx}] source={it.source_label} | title={it.title} | summary={(it.summary or '')[:300]}"
        )
    user = (
        f"PRODUCT PROFILE:\n{profile}\n\nRAW NEWS ITEMS:\n" + "\n".join(lines)
    )
    user = context_feed.augment(
        user, context_feed.build_context_block(db, product_id=product.id)
    )

    try:
        result = llm.complete_json(_SYSTEM, user, settings_cfg=settings.get_llm(db), max_tokens=1500)
    except Exception as exc:
        log.warning("news relevance pass failed for %s: %s", product.full_name, exc)
        return []

    scored = []
    for entry in (result.get("items", []) if isinstance(result, dict) else []):
        try:
            idx = int(entry.get("index"))
            rel = float(entry.get("relevance", 0.0))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(raw_items):
            continue
        if rel < threshold:
            continue
        if not entry.get("title"):
            continue
        scored.append((rel, raw_items[idx], entry))

    # Highest relevance first, cap at top_n. top_n is per product per run.
    scored.sort(key=lambda t: t[0], reverse=True)
    scored = scored[:top_n]

    if not scored:
        # Nothing cleared the bar. Still mark the batch processed so it isn't re-judged.
        repository.mark_news_processed(db, [it.id for it in raw_items])
        return []

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

    # Mark ALL raw items in this batch processed (judged, whether or not promoted).
    repository.mark_news_processed(db, [it.id for it in raw_items])
    return questions
