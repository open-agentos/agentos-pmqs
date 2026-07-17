"""api/products.py — Add Product flow + product listing (issue #53).

POST /products          -> resolve-or-create a Product by org/repo, kick off the
                            initial seed lens pass (#54), redirect.
GET  /api/workspaces     -> JSON list of this account's products (feeds the Product
                            switcher, #55). Route path kept as /api/workspaces --
                            renaming the URL is item 5's call (session -> workspace),
                            not this item's; the underlying model is Product.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import members, products
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
def add_product(
    repo: str = Form(...),
    nickname: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    """Add a product to the PM's account.

    `repo` is an 'org/repo' reference. Resolves against the existing Product row if
    another PM already registered this repo (shared Product via Membership);
    creates a new Product row otherwise.
    """
    try:
        org, repo_name = products.parse_repo_ref(repo)
    except ValueError:
        return RedirectResponse(url="/products/new?product_error=invalid_repo", status_code=303)

    product = products.get_or_create_product(
        db, org=org, repo=repo_name, display_name=repo_name, nickname=nickname or None
    )

    # Attach the acting PM to the Product. get_or_create_product resolving to an EXISTING
    # row is the shared-Product case (two PMs, same repo, one Product) -- that's exactly
    # when a Membership is most needed, so this runs on resolve as well as on create.
    # Before #99 nothing on this path called it at all: only db.py's backfill ever made
    # a Membership row, so every product added through the UI had none. Invisible only
    # because list_products isn't membership-scoped either.
    member = db.get(Member, members.current_member_id(db))
    members.ensure_membership(db, member=member, product=product, role="owner")

    # Seed the new product's inbox immediately rather than waiting for tomorrow's
    # scheduled batch (#54).
    from pmqs.pipeline import seed_workspace

    seed_workspace(db, product)

    # Land on the product you just added -- specifically, on its Settings, because Add
    # Product ends exactly where Product Settings begins: the watchlist and profile that
    # make it useful are the next thing you need. Until #99 this redirected to "/",
    # i.e. a DIFFERENT product's inbox, on a stale "#56 lands later" comment.
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
