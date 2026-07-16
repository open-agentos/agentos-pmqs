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
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import products
from pmqs.db import get_session

router = APIRouter()


@router.post("/products")
def add_product(
    repo: str = Form(...),
    nickname: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    """Add a product to the PM's account.

    `repo` is an 'org/repo' reference. Resolves against the existing Product row if
    another PM already registered this repo (shared Product via Membership);
    creates a new Product row otherwise. Malformed refs redirect back to Settings
    with an error flag rather than a 500 -- this is a hand-typed form field for now.
    """
    try:
        org, repo_name = products.parse_repo_ref(repo)
    except ValueError:
        return RedirectResponse(url="/settings?product_error=invalid_repo", status_code=303)

    product = products.get_or_create_product(db, org=org, repo=repo_name, display_name=repo_name, nickname=nickname or None)

    # Seed the new product's inbox immediately rather than waiting for tomorrow's
    # scheduled batch (#54).
    from pmqs.pipeline import seed_workspace

    seed_workspace(db, product)

    # Product-scoped navigation (/w/{slug}/...) lands in #56; for now land back on
    # the existing single Inbox view. A proper "Product added" confirmation belongs
    # with the switcher UI (#55) rather than overloading the news-flash query param.
    return RedirectResponse(url="/", status_code=303)


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
