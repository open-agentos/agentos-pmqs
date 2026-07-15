"""api/news.py — news ingestion + relevance routes (Phase 4).

POST /news/ingest → fetch configured Brave queries + run the interpretive relevance pass,
then redirect to the Inbox with a short flash message (?news=<n> or ?news=none).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session as OrmSession

from pmqs.db import get_session
from pmqs.news.fetch import ingest
from pmqs.news.relevance import promote_relevant

router = APIRouter()


@router.post("/news/ingest")
def news_ingest(db: OrmSession = Depends(get_session)):
    # Fetch raw items (dedup by URL), then run the batched relevance pass.
    ingest(db)
    promoted = promote_relevant(db)
    n = len(promoted)
    flash = str(n) if n else "none"
    return RedirectResponse(url=f"/?news={flash}", status_code=303)
