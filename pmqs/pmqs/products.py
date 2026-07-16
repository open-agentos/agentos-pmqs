"""products.py — Product repository (multi-product model, build-spec).

Product is the tenant-scoped unit peers join (build-spec §3): repos, watchlist, lens
weights, slug/nickname all live here. Peer-sharing across PMs is via Membership
(members.py), not via separate Product rows for the same repo -- see the fold
described in models.Product's docstring (build-spec §8 step 2).
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from pmqs.models import Product


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "product"


def parse_repo_ref(ref: str) -> tuple[str, str]:
    """Split an 'org/repo' string into (org, repo). Raises ValueError if malformed."""
    parts = ref.strip().strip("/").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Expected 'org/repo', got {ref!r}")
    return parts[0], parts[1]


def _next_free_slug(db: OrmSession, base_slug: str) -> str:
    slug = base_slug
    n = 2
    while db.scalars(select(Product).where(Product.slug == slug)).first() is not None:
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


def get_or_create_product(
    db: OrmSession,
    *,
    org: str,
    repo: str,
    display_name: str | None = None,
    nickname: str | None = None,
    lens_weights: dict[str, Any] | None = None,
) -> Product:
    """Resolve a Product by (org, repo), creating it if this is the first PM to add it.

    This is what lets two different PMs add the same repo and end up as Members of
    the SAME Product (see members.ensure_membership) rather than each getting their
    own disconnected copy.
    """
    existing = db.scalars(
        select(Product).where(Product.org == org).where(Product.repo == repo)
    ).first()
    if existing is not None:
        return existing
    base_slug = _slugify(nickname or repo)
    product = Product(
        org=org,
        repo=repo,
        display_name=display_name or repo,
        nickname=nickname,
        slug=_next_free_slug(db, base_slug),
        lens_weights=json.dumps(lens_weights) if lens_weights is not None else None,
    )
    db.add(product)
    db.commit()
    return product


def get_product(db: OrmSession, product_id: str) -> Product | None:
    return db.get(Product, product_id)


def get_product_by_slug(db: OrmSession, slug: str) -> Product | None:
    return db.scalars(select(Product).where(Product.slug == slug)).first()


def list_products(db: OrmSession, *, include_archived: bool = False) -> list[Product]:
    stmt = select(Product)
    if not include_archived:
        stmt = stmt.where(Product.archived.is_(False))
    stmt = stmt.order_by(Product.created_at)
    return list(db.scalars(stmt))


def product_display_name(db: OrmSession, product: Product) -> str:
    if product.nickname:
        return product.nickname
    return product.display_name or product.slug or product.full_name


def get_or_create_default_product(db: OrmSession) -> Product:
    """Return the account's first (oldest) Product, creating one against
    config.AGENTOS_REPO if none exists yet. Used for the Phase-0 backfill and as the
    fallback for routes that don't specify a Product explicitly.
    """
    from pmqs import config

    existing = list_products(db, include_archived=True)
    if existing:
        return existing[0]
    org, repo = parse_repo_ref(config.AGENTOS_REPO)
    return get_or_create_product(db, org=org, repo=repo, display_name=repo)


def resolve_product_id(db: OrmSession, product_slug: str | None) -> str | None:
    """Turn an optional `product_slug` path param into a concrete product_id.

    Used by every route that supports BOTH the legacy unprefixed path (no slug --
    returns None, meaning "no product filter", the pre-#56 behaviour) and the
    `/w/{product_slug}/...` path (see #56 -- resolves to that product's id).
    Raises KeyError if the slug doesn't match any product, which routes translate to
    a 404.
    """
    if product_slug is None:
        return None
    p = get_product_by_slug(db, product_slug)
    if p is None:
        raise KeyError(product_slug)
    return p.id
