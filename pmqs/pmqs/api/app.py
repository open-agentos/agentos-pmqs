"""FastAPI app — Phase 0 render + Phase 0.5/1 routes."""
from __future__ import annotations

from fastapi import FastAPI

from pmqs.api.inbox import router as inbox_router
from pmqs.api.outcomes import router as outcomes_router
from pmqs.db import init_db

app = FastAPI(title="PMQs", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


app.include_router(inbox_router)
app.include_router(outcomes_router)
