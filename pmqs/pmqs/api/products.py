"""api/products.py — Add Product flow + product listing (issue #53).

POST /products          -> resolve-or-create a Product by org/repo, kick off the
                            initial seed lens pass (#54), redirect.
GET  /api/workspaces     -> JSON list of this account's products (feeds the Product
                            switcher, #55). Route path kept as /api/workspaces --
                            renaming the URL is item 5's call (session -> workspace),
                            not this item's; the underlying model is Product.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import members, products
from pmqs.api.product_form import apply_product_config
from pmqs.db import get_session
from pmqs.models import Member
from pmqs.web.render import render_product_settings

router = APIRouter()


@router.get("/products/new", response_class=HTMLResponse)
def new_product_page(product_error: str | None = None, db: OrmSession = Depends(get_session)):
    """Add Product is Product Settings with an empty Product (#99). Same renderer, same
    fields, mode="create" -- because everything you'd set when adding is everything
    you'd edit later."""
    return HTMLResponse(render_product_settings(db, None, mode="create", flash=product_error))


@router.post("/products")
async def add_product(request: Request, db: OrmSession = Depends(get_session)):
    """Add a product to the PM's account.

    The create form is Product Settings in create mode (#99): it renders the full
    watchlist / profile / lens set, and the onboarding research pass (see
    docs/build-spec-product-onboarding.md) pre-populates them. So this reads the whole
    form, not just repo/nickname -- persisting only what was dropped before.

    `repo` is an 'org/repo' reference. Resolves against the existing Product row if
    another PM already registered this repo (shared Product via Membership); creates a
    new Product row otherwise.
    """
    form = await request.form()
    repo = (form.get("repo") or "").strip()
    display_name = (form.get("display_name") or "").strip()
    nickname = (form.get("nickname") or "").strip()

    try:
        org, repo_name = products.parse_repo_ref(repo)
    except ValueError:
        return RedirectResponse(url="/products/new?product_error=invalid_repo", status_code=303)

    # Did this repo already exist? get_or_create_product would resolve to it silently;
    # we need to know BEFORE, so we don't write this PM's researched watchlist/profile
    # over a colleague's existing product (the shared-Product resolve case).
    created = products.get_product_by_org_repo(db, org, repo_name) is None

    product = products.get_or_create_product(
        db, org=org, repo=repo_name,
        display_name=display_name or repo_name, nickname=nickname or None,
    )

    # Attach the acting PM to the Product. get_or_create_product resolving to an EXISTING
    # row is the shared-Product case (two PMs, same repo, one Product) -- that's exactly
    # when a Membership is most needed, so this runs on resolve as well as on create.
    member = db.get(Member, members.current_member_id(db))
    members.ensure_membership(db, member=member, product=product, role="owner")

    if created:
        # Persist the entered/researched config -- but ONLY on a product we just made.
        # Applied BEFORE seed_workspace so the first seed pass runs against the real
        # watchlist and profile instead of an empty product.
        apply_product_config(
            db, product,
            wl_industry=form.get("wl_industry", ""),
            wl_keywords=form.get("wl_keywords", ""),
            wl_companies=form.get("wl_companies", ""),
            wl_products=form.get("wl_products", ""),
            wl_sources=form.get("wl_sources", ""),
            news_queries=form.get("news_queries", ""),
            product_profile=form.get("product_profile", ""),
            website=(form.get("website") or "").strip() or None,
            lens_form=form,
        )

    # Seed the new product's inbox immediately rather than waiting for tomorrow's
    # scheduled batch (#54).
    from pmqs.pipeline import seed_workspace

    seed_workspace(db, product)

    # Land on the product you just added -- specifically, on its Settings, because Add
    # Product ends exactly where Product Settings begins.
    return RedirectResponse(url=f"/w/{product.slug}/settings?added=1", status_code=303)


@router.get("/api/workspaces")
def list_workspaces(db: OrmSession = Depends(get_session)):
    rows = products.list_products(db)
    return JSONResponse(
        [
            {
                "id": p.id,
                "slug": p.slug,
                "display_name": products.product_display_name(db, p),
                "product_id": p.id,
                "product_repo": p.full_name,
            }
            for p in rows
        ]
    )
