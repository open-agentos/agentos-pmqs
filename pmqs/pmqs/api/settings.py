"""api/settings.py — Settings panel routes (Phase 2). LLM section first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import settings as settings_mod
from pmqs.db import get_session
from pmqs.web.render import render_settings

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(db: OrmSession = Depends(get_session)):
    return HTMLResponse(render_settings(db))


@router.post("/settings")
def save_settings(
    provider: str = Form(...),
    model: str = Form(...),
    api_key_ref: str = Form(default=""),
    api_key_raw: str = Form(default=""),
    base_url: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    # Preserve an existing inline key if the field was left blank.
    if not api_key_raw:
        current = settings_mod.get_llm(db)
        api_key_raw = current.get("api_key_raw", "")
    # The masked placeholder must not be persisted back as a ref.
    if api_key_ref.startswith("•"):
        api_key_ref = settings_mod.get_llm(db).get("api_key_ref", "")
    settings_mod.set_llm(
        db, provider=provider, model=model,
        api_key_ref=api_key_ref, api_key_raw=api_key_raw, base_url=base_url,
    )
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/news")
def save_news_settings(
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
    if news_api_key_ref.startswith("•"):
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
    return RedirectResponse(url="/settings", status_code=303)
