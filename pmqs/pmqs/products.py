"""products.py — Product/Workspace repository (multi-product model, build-spec).

Product is global/shared, keyed by (org, repo). Workspace is the private, per-PM
decision-loop boundary against one Product. Kept in its own module (like settings.py)
rather than folded into repository.py, since it's a distinct concern from
Questions/Outcomes/Sessions.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from pmqs.models import Product, Workspace

# Single hardcoded account until real multi-tenant auth (Phase 5).
DEFAULT_ACCOUNT_ID = "default"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "workspace"


def parse_repo_ref(ref: str) -> tuple[str, str]:
    """Split an 'org/repo' string into (org, repo). Raises ValueError if malformed."""
    parts = ref.strip().strip("/").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Expected 'org/repo', got {ref!r}")
    return parts[0], parts[1]


def get_or_create_product(db: OrmSession, *, org: str, repo: str, display_name: str | None = None) -> Product:
    """Resolve a Product by (org, repo), creating it if this is the first PM to add it.

    This is what lets two different PMs add the same repo and share the Product row
    while keeping their own Workspaces (and therefore their own Questions/Outcomes/
    Policies) fully separate.
    """
    existing = db.scalars(
        select(Product).where(Product.org == org).where(Product.repo == repo)
    ).first()
    if existing is not None:
        return existing
    product = Product(org=org, repo=repo, display_name=display_name or repo)
    db.add(product)
    db.commit()
    return product


def get_product(db: OrmSession, product_id: str) -> Product | None:
    return db.get(Product, product_id)


def create_workspace(
    db: OrmSession,
    *,
    product: Product,
    account_id: str = DEFAULT_ACCOUNT_ID,
    nickname: str | None = None,
    lens_weights: dict[str, Any] | None = None,
) -> Workspace:
    """Create a new Workspace (this PM's private view of `product`).

    Slug is derived from the product's repo name, disambiguated with a numeric suffix
    if this account already has a workspace with that slug (e.g. two products that
    happen to share a repo basename across orgs).
    """
    base_slug = _slugify(nickname or product.repo)
    slug = base_slug
    n = 2
    while db.scalars(select(Workspace).where(Workspace.slug == slug)).first() is not None:
        slug = f"{base_slug}-{n}"
        n += 1
    ws = Workspace(
        account_id=account_id,
        product_id=product.id,
        slug=slug,
        nickname=nickname,
        lens_weights=json.dumps(lens_weights) if lens_weights is not None else None,
    )
    db.add(ws)
    db.commit()
    return ws


def get_workspace(db: OrmSession, workspace_id: str) -> Workspace | None:
    return db.get(Workspace, workspace_id)


def get_workspace_by_slug(db: OrmSession, slug: str) -> Workspace | None:
    return db.scalars(select(Workspace).where(Workspace.slug == slug)).first()


def list_workspaces(db: OrmSession, *, account_id: str = DEFAULT_ACCOUNT_ID, include_archived: bool = False) -> list[Workspace]:
    stmt = select(Workspace).where(Workspace.account_id == account_id)
    if not include_archived:
        stmt = stmt.where(Workspace.archived.is_(False))
    stmt = stmt.order_by(Workspace.added_at)
    return list(db.scalars(stmt))


def workspace_display_name(db: OrmSession, workspace: Workspace) -> str:
    if workspace.nickname:
        return workspace.nickname
    product = get_product(db, workspace.product_id)
    return product.display_name if product else workspace.slug


def get_or_create_default_workspace(db: OrmSession) -> Workspace:
    """Return the account's first (oldest) workspace, creating one against
    config.AGENTOS_REPO if none exists yet. Used for the Phase-0 backfill and as the
    fallback for routes that don't specify a workspace explicitly.
    """
    from pmqs import config

    existing = list_workspaces(db, include_archived=True)
    if existing:
        return existing[0]
    org, repo = parse_repo_ref(config.AGENTOS_REPO)
    product = get_or_create_product(db, org=org, repo=repo, display_name=repo)
    return create_workspace(db, product=product)
