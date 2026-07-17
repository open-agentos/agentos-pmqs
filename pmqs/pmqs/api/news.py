"""api/news.py — news ingestion + relevance routes (Phase 4).

POST /news/ingest → fetch the configured queries + run the interpretive relevance pass,
then redirect back where you came from with a short flash (?news=<n> or ?news=none).
Default is the Inbox; Settings passes return_to so its Fetch-now button doesn't throw
you out of the page it's on (#92).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs import settings
from pmqs.db import get_session
from pmqs.news.fetch import ingest
from pmqs.news.relevance import promote_relevant

router = APIRouter()


@router.post("/news/ingest")
@router.post("/w/{workspace_slug}/news/ingest")
def news_ingest(
    workspace_slug: str | None = None,
    return_to: str = Form(default=""),
    db: OrmSession = Depends(get_session),
):
    # Fetch raw items (dedup by URL), then run the batched relevance pass.
    ingest(db)
    promoted = promote_relevant(db)
    n = len(promoted)
    settings.record_news_run(db, promoted=n)
    flash = str(n) if n else "none"
    # Relative paths only -- return_to comes off a form and lands in a Location header.
    dest = return_to if return_to.startswith("/") and not return_to.startswith("//") else None
    if dest is None:
        dest = f"/w/{workspace_slug}/" if workspace_slug else "/"
    sep = "&" if "?" in dest else "?"
    return RedirectResponse(url=f"{dest}{sep}news={flash}", status_code=303)
