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
from pmqs.web.render import render_error, render_settings

router = APIRouter()


def _back(workspace_slug: str | None) -> str:
    return f"/w/{workspace_slug}/settings" if workspace_slug else "/settings"


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
    news_api_key_ref: str = Form(default="BRAVE_API_KEY"),
    news_api_key_raw: str = Form(default=""),
    news_queries: str = Form(default=""),
    product_profile: str = Form(default=""),
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
    queries = [q.strip() for q in news_queries.splitlines() if q.strip()]
    try:
        top_n_i = int(top_n)
    except ValueError:
        top_n_i = current.get("top_n", 3)
    try:
        thresh_f = float(min_relevance)
    except ValueError:
        thresh_f = current.get("min_relevance", 0.5)
    settings_mod.set_news_config(
        db,
        api_key_ref=news_api_key_ref,
        api_key_raw=news_api_key_raw,
        queries=queries,
        product_profile=product_profile,
        top_n=top_n_i,
        min_relevance=thresh_f,
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
