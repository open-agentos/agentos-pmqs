"""api/settings.py — Settings routes.

Settings renders inside the app shell (#90), same as the Inbox/Workspace/Outcomes
views. Every route carries a `/w/{workspace_slug}/...` twin (#56): the slug does NOT
scope any config -- Settings is account-wide -- it only keeps the rail's Product
switcher and nav links pointing at whichever product the PM walked in from. Without
it, opening Settings from a workspace silently drops you out of that workspace.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import members, products
from pmqs import settings as settings_mod
from pmqs.db import get_session
from pmqs.news.watchlist import parse_field
from pmqs.web.render import render_error, render_settings

router = APIRouter()


def _back(workspace_slug: str | None) -> str:
    return f"/w/{workspace_slug}/settings" if workspace_slug else "/settings"


def _current_product(db: OrmSession, workspace_slug: str | None):
    """Same rule the switcher and render_settings use: explicit slug wins, else the
    account's default product. None only when no products exist yet."""
    if workspace_slug is not None:
        return products.get_product_by_slug(db, workspace_slug)
    all_products = products.list_products(db)
    return all_products[0] if all_products else None


@router.get("/settings", response_class=HTMLResponse)
@router.get("/w/{workspace_slug}/settings", response_class=HTMLResponse)
def settings_page(workspace_slug: str | None = None, db: OrmSession = Depends(get_session)):
    if workspace_slug is not None and products.get_product_by_slug(db, workspace_slug) is None:
        return HTMLResponse(render_error(f"No such product workspace: {workspace_slug}", 404), status_code=404)
    return HTMLResponse(render_settings(db, workspace_slug=workspace_slug))


@router.post("/settings")
@router.post("/w/{workspace_slug}/settings")
def save_settings(
    workspace_slug: str | None = None,
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
    # Preserve an existing inline key if the field was left blank.
    if not api_key_raw:
        current = settings_mod.get_llm(db)
        api_key_raw = current.get("api_key_raw", "")
    # The masked placeholder must not be persisted back as a ref.
    if api_key_ref.startswith("\u2022"):
        api_key_ref = settings_mod.get_llm(db).get("api_key_ref", "")
    settings_mod.set_llm(
        db, provider=provider, model=model,
        api_key_ref=api_key_ref, api_key_raw=api_key_raw, base_url=base_url,
    )
    return RedirectResponse(url=_back(workspace_slug), status_code=303)


@router.post("/settings/news")
@router.post("/w/{workspace_slug}/settings/news")
def save_news_settings(
    workspace_slug: str | None = None,
    news_enabled: str = Form(default=""),
    news_api_key_ref: str = Form(default="BRAVE_API_KEY"),
    news_api_key_raw: str = Form(default=""),
    wl_industry: str = Form(default=""),
    wl_keywords: str = Form(default=""),
    wl_companies: str = Form(default=""),
    wl_products: str = Form(default=""),
    wl_sources: str = Form(default=""),
    news_queries: str = Form(default=""),
    product_profile: str = Form(default=""),
    count: str = Form(default="10"),
    freshness: str = Form(default="pw"),
    top_n: str = Form(default="3"),
    min_relevance: str = Form(default="0.5"),
    db: OrmSession = Depends(get_session),
):
    current = settings_mod.get_news_config(db)
    # Preserve an existing inline key if the field was left blank.
    if not news_api_key_raw:
        news_api_key_raw = current.get("api_key_raw", "")
    # The masked placeholder must not be persisted back as a ref.
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

    # The watchlist and the profile belong to the Product, not the account (#96).
    product = _current_product(db, workspace_slug)
    if product is not None:
        products.set_news_config(
            db, product,
            watchlist={
                "industry": parse_field(wl_industry),
                "keywords": parse_field(wl_keywords),
                "companies": parse_field(wl_companies),
                "products": parse_field(wl_products),
                "sources": parse_field(wl_sources),
            },
            queries=parse_field(news_queries),
            product_profile=product_profile,
        )
    return RedirectResponse(url=_back(workspace_slug), status_code=303)


@router.post("/settings/advanced")
@router.post("/w/{workspace_slug}/settings/advanced")
def save_advanced_settings(
    workspace_slug: str | None = None,
    char_budget: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    """The context-feed budget. The store (settings.get/set_context_budget) has existed
    since Phase 3 with no caller and no UI; this is the caller."""
    try:
        settings_mod.set_context_budget(db, int(char_budget))
    except (TypeError, ValueError):
        pass  # unparseable -> keep the current value rather than zeroing the feed
    return RedirectResponse(url=_back(workspace_slug), status_code=303)
