"""api/product_form.py — one parser for the Product config form.

Add Product (create) and Product Settings (edit) render the SAME fields (#99) and must
persist them the same way. Before this, only the edit route parsed them; add_product
dropped everything but repo/nickname, so a create form that showed a watchlist quietly
discarded it. Both routes now funnel through here so the two can't drift apart.

Pure-ish: no request objects. The caller hands in already-extracted strings plus a
mapping for the lens fields (whose set lives in config.LENS_WEIGHTS, not a fixed
signature, so it can't be enumerated as Form params without drifting from config).
"""
from __future__ import annotations

from typing import Any, Mapping

from pmqs import config, products
from pmqs.news.watchlist import parse_field


def lens_overrides(form: Mapping[str, Any] | None) -> dict[str, float]:
    """Read the 8 lens weights off a raw form mapping.

    A missing or unparseable field is skipped (keeps the product's current/default
    weight) rather than zeroing that lens -- same rule the edit route already used.
    """
    weights: dict[str, float] = {}
    if not form:
        return weights
    for lens in config.LENS_WEIGHTS:
        raw = form.get(f"lens_{lens}")
        if raw in (None, ""):
            continue
        try:
            weights[lens] = float(raw)
        except (TypeError, ValueError):
            continue
    return weights


def apply_product_config(
    db: Any,
    product: products.Product,
    *,
    wl_industry: str = "",
    wl_keywords: str = "",
    wl_companies: str = "",
    wl_products: str = "",
    wl_sources: str = "",
    news_queries: str = "",
    product_profile: str = "",
    website: str | None = None,
    lens_form: Mapping[str, Any] | None = None,
) -> None:
    """Persist the watchlist, profile, website and lens weights onto `product`.

    `website=None` preserves whatever is stored (set_news_config's rule) so an edit save
    with no website field doesn't wipe it.
    """
    products.set_news_config(
        db,
        product,
        watchlist={
            "industry": parse_field(wl_industry),
            "keywords": parse_field(wl_keywords),
            "companies": parse_field(wl_companies),
            "products": parse_field(wl_products),
            "sources": parse_field(wl_sources),
        },
        queries=parse_field(news_queries),
        product_profile=product_profile,
        website=website,
    )
    products.set_lens_weights(db, product, lens_overrides(lens_form))
