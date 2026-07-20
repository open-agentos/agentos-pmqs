"""Public logged-out entry point; OAuth is a future implementation."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from pmqs.web.render import render_login

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login() -> HTMLResponse:
    return HTMLResponse(render_login())
