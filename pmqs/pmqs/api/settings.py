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
