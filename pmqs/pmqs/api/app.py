"""FastAPI app — Phase 0 render + Phase 0.5/1 routes + Phase 2 workspace/settings."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from pmqs.api.brand import router as brand_router
from pmqs.api.inbox import router as inbox_router
from pmqs.api.news import router as news_router
from pmqs.api.outcomes import router as outcomes_router
from pmqs.api.products import router as products_router
from pmqs.api.settings import router as settings_router
from pmqs.api.workspace import router as workspace_router
from pmqs.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PMQs", version="0.1.0", lifespan=lifespan)

app.include_router(brand_router)
app.include_router(inbox_router)
app.include_router(outcomes_router)
app.include_router(products_router)
app.include_router(settings_router)
app.include_router(workspace_router)
app.include_router(news_router)
