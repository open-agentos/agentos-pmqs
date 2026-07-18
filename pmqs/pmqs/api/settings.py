"""api/settings.py — Settings routes.

TWO SURFACES, split along the line between you and the product (#98):

  GET/POST /settings[...]           -> ACCOUNT. Unprefixed on purpose: it scopes to no
                                       product. Reached from the identity block.
  GET/POST /w/{slug}/settings[...]  -> PRODUCT. Reached from the Product switcher.

Before this, /w/{slug}/settings rendered ACCOUNT settings -- a URL carrying a product
prefix that scoped nothing with it. The prefix now means here what it means everywhere
else in the app.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import members, products
from pmqs import settings as settings_mod
from pmqs.api.product_form import apply_product_config
from pmqs.db import get_session
from pmqs.web.render import render_error, render_product_settings, render_settings

router = APIRouter()


def _not_found(slug: str) -> HTMLResponse:
    return HTMLResponse(render_error(f"No such product workspace: {slug}", 404), status_code=404)


# --------------------------------------------------------------------------- account


@router.get("/settings", response_class=HTMLResponse)
def settings_page(db: OrmSession = Depends(get_session)):
    return HTMLResponse(render_settings(db))


@router.post("/settings")
def save_settings(
    display_name: str = Form(default=""),
    provider: str = Form(...),
    model: str = Form(...),
    api_key_ref: str = Form(default=""),
    api_key_raw: str = Form(default=""),
    base_url: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    if display_name:
        members.set_display_name(db, member_id=members.current_member_id(db),
                                 display_name=display_name)
    current = settings_mod.get_llm(db)
    # Preserve an existing inline key if the field was left blank.
    if not api_key_raw:
        api_key_raw = current.get("api_key_raw", "")
    # The masked placeholder must not be persisted back as a ref.
    if api_key_ref.startswith("\u2022"):
        api_key_ref = current.get("api_key_ref", "")
    settings_mod.set_llm(
        db, provider=provider, model=model,
        api_key_ref=api_key_ref, api_key_raw=api_key_raw, base_url=base_url,
    )
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/news")
def save_news_settings(
    news_enabled: str = Form(default=""),
    news_api_key_ref: str = Form(default="BRAVE_API_KEY"),
    news_api_key_raw: str = Form(default=""),
    count: str = Form(default="10"),
    freshness: str = Form(default="pw"),
    top_n: str = Form(default="3"),
    min_relevance: str = Form(default="0.5"),
    db: OrmSession = Depends(get_session),
):
    """The Brave key and the throttles. The watchlist is the Product's (#96)."""
    current = settings_mod.get_news_config(db)
    if not news_api_key_raw:
        news_api_key_raw = current.get("api_key_raw", "")
    if news_api_key_ref.startswith("\u2022"):
        news_api_key_ref = current.get("api_key_ref", "BRAVE_API_KEY")

    def _num(raw: str, cast, key: str):
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return current.get(key)

    settings_mod.set_news_config(
        db,
        api_key_ref=news_api_key_ref,
        api_key_raw=news_api_key_raw,
        # An unchecked checkbox posts nothing at all, so absence IS off.
        enabled=bool(news_enabled),
        count=_num(count, int, "count"),
        freshness=freshness if freshness in dict(settings_mod.FRESHNESS_CHOICES) else current.get("freshness", "pw"),
        top_n=_num(top_n, int, "top_n"),
        min_relevance=_num(min_relevance, float, "min_relevance"),
    )
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/advanced")
def save_advanced_settings(
    char_budget: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    """The context-feed budget. The store has existed since Phase 3 with no caller."""
    try:
        settings_mod.set_context_budget(db, int(char_budget))
    except (TypeError, ValueError):
        pass  # unparseable -> keep the current value rather than zeroing the feed
    return RedirectResponse(url="/settings", status_code=303)


# --------------------------------------------------------------------------- product


@router.get("/w/{workspace_slug}/settings", response_class=HTMLResponse)
def product_settings_page(workspace_slug: str, product_error: str | None = None,
                          added: str | None = None, db: OrmSession = Depends(get_session)):
    product = products.get_product_by_slug(db, workspace_slug)
    if product is None:
        return _not_found(workspace_slug)
    return HTMLResponse(render_product_settings(
        db, product, workspace_slug=workspace_slug,
        flash=product_error or ("added" if added else None),
    ))


@router.post("/w/{workspace_slug}/settings")
async def save_product_settings(
    workspace_slug: str,
    display_name: str = Form(default=""),
    nickname: str = Form(default=""),
    repo: str = Form(default=""),
    wl_industry: str = Form(default=""),
    wl_keywords: str = Form(default=""),
    wl_companies: str = Form(default=""),
    wl_products: str = Form(default=""),
    wl_sources: str = Form(default=""),
    news_queries: str = Form(default=""),
    product_profile: str = Form(default=""),
    request: Request = None,
    db: OrmSession = Depends(get_session),
):
    """One form, one save: everything that belongs to this Product."""
    product = products.get_product_by_slug(db, workspace_slug)
    if product is None:
        return _not_found(workspace_slug)

    try:
        products.update_product(db, product, display_name=display_name,
                                nickname=nickname, repo=repo)
    except ValueError:
        return RedirectResponse(url=f"/w/{workspace_slug}/settings?product_error=invalid_repo",
                                status_code=303)

    # The watchlist, profile and 8 lens weights share one parser with Add Product
    # (api/product_form) so the create and edit paths can't drift. The lens set lives in
    # config.LENS_WEIGHTS, not a fixed signature; a missing/unparseable field keeps the
    # current weight rather than zeroing that lens. website is not a field here, so it's
    # preserved (apply_product_config passes website=None -> keep stored).
    form = await request.form() if request is not None else {}
    apply_product_config(
        db, product,
        wl_industry=wl_industry, wl_keywords=wl_keywords, wl_companies=wl_companies,
        wl_products=wl_products, wl_sources=wl_sources, news_queries=news_queries,
        product_profile=product_profile, lens_form=form,
    )
    return RedirectResponse(url=f"/w/{workspace_slug}/settings", status_code=303)


@router.post("/w/{workspace_slug}/settings/archive")
def archive_product(workspace_slug: str, db: OrmSession = Depends(get_session)):
    product = products.get_product_by_slug(db, workspace_slug)
    if product is None:
        return _not_found(workspace_slug)
    products.set_archived(db, product, archived=True)
    # It's gone from the switcher, so there's nowhere inside it to go back to.
    return RedirectResponse(url="/", status_code=303)
