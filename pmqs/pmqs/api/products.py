"""api/products.py — Add Product flow + workspace listing (issue #53).

POST /products          -> resolve-or-create a Product by org/repo, create a Workspace
                            for it, kick off the initial seed lens pass (#54), redirect.
GET  /api/workspaces     -> JSON list of this account's workspaces (feeds the Product
                            switcher, #55).
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
    another PM already registered this repo (shared Product, separate Workspace);
    creates a new Product row otherwise. Malformed refs redirect back to Settings
    with an error flag rather than a 500 -- this is a hand-typed form field for now.
    """
    try:
        org, repo_name = products.parse_repo_ref(repo)
    except ValueError:
        return RedirectResponse(url="/settings?product_error=invalid_repo", status_code=303)

    product = products.get_or_create_product(db, org=org, repo=repo_name, display_name=repo_name)
    workspace = products.create_workspace(db, product=product, nickname=nickname or None)

    # Note: this doesn't yet trigger an immediate seed lens pass for the new workspace
    # -- that's #54, landing as a follow-up PR so this one stays scoped to resolve-or-
    # create + Workspace creation. Until #54 merges, a fresh workspace's inbox stays
    # empty until the next scheduled daily batch.

    # Workspace-scoped navigation (/w/{slug}/...) lands in #56; for now land back on
    # the existing single Inbox view. A proper "Product added" confirmation belongs
    # with the switcher UI (#55) rather than overloading the news-flash query param.
    return RedirectResponse(url="/", status_code=303)


@router.get("/api/workspaces")
def list_workspaces(db: OrmSession = Depends(get_session)):
    rows = products.list_workspaces(db)
    return JSONResponse(
        [
            {
                "id": ws.id,
                "slug": ws.slug,
                "display_name": products.workspace_display_name(db, ws),
                "product_id": ws.product_id,
                "product_repo": products.get_product(db, ws.product_id).full_name
                if products.get_product(db, ws.product_id) else None,
            }
            for ws in rows
        ]
    )
