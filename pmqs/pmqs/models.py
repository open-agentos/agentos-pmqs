"""models.py — ORM models matching the Phase 0.5 schema in build-spec-phase-0-1.md.

JSON-ish columns (lens_tags, evidence, score_dims, payload) are stored as TEXT and
serialized/deserialized via helpers to stay Postgres-swap friendly.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ForeignKey, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from pmqs.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    lens_tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")   # JSON array
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="[]")    # JSON array
    score: Mapped[float | None] = mapped_column(Float)
    score_dims: Mapped[str | None] = mapped_column(Text)                          # JSON object
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")  # proposed|saved|dismissed|promoted
    source: Mapped[str] = mapped_column(Text, nullable=False)                     # system|pm
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)

    # --- JSON helpers ---
    @property
    def lens_tags_list(self) -> list[str]:
        return json.loads(self.lens_tags or "[]")

    @property
    def evidence_list(self) -> list[dict[str, Any]]:
        return json.loads(self.evidence or "[]")

    @property
    def score_dims_dict(self) -> dict[str, Any]:
        return json.loads(self.score_dims or "{}")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    topic: Mapped[str | None] = mapped_column(Text)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))  # branching
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")  # open | closed
    position_doc: Mapped[str | None] = mapped_column(Text)  # JSON, generate-once (Phase 2)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    closed_at: Mapped[str | None] = mapped_column(Text)


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # system | pm | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON value


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # issue|policy|document|meeting|question
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    github_ref: Mapped[str | None] = mapped_column(Text)  # only for type='issue' after push
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
