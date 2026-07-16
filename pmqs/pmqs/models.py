"""models.py — ORM models matching the Phase 0.5 schema in build-spec-phase-0-1.md.

JSON-ish columns (lens_tags, evidence, score_dims, payload) are stored as TEXT and
serialized/deserialized via helpers to stay Postgres-swap friendly.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Text, Float, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pmqs.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    lens_tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")   # JSON array
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="[]")    # JSON array
    score: Mapped[float | None] = mapped_column(Float)
    score_dims: Mapped[str | None] = mapped_column(Text)                          # JSON object
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")  # proposed|saved|dismissed|promoted
    source: Mapped[str] = mapped_column(Text, nullable=False)                     # system|pm|news
    origin_session_id: Mapped[str | None] = mapped_column(Text)  # war-room session that produced it (lens output)
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
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
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


class NewsItem(Base):
    """Raw news item (Phase 4). Staging store OUTSIDE the Issues substrate and separate
    from `questions` — raw material is not evidence until promoted to a Question. Must
    never be written to GitHub.

    KNOWN GAP from the #52 workspace-scoping pass: `url` is still globally unique, not
    (workspace_id, url). Harmless while news ingestion (Phase 4) isn't live, but once
    it is, two workspaces that both watch the same story will dedupe against each
    other incorrectly. Needs a table rebuild to fix (SQLite can't ALTER a UNIQUE
    constraint in place) -- left for whoever picks Phase 4 back up.
    """

    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    source_label: Mapped[str] = mapped_column(Text, nullable=False, default="")  # e.g. query or publisher
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # dedup key
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Product(Base):
    """A GitHub-primitives repo PMQs can point at (build-spec: multi-product model).

    Global/shared -- keyed by (org, repo) so two PMs pointing at the same repo resolve
    to the same Product row rather than duplicating it. A Product carries no PM's
    private decision data; see Workspace for that.
    """

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("org", "repo", name="uq_products_org_repo"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    org: Mapped[str] = mapped_column(Text, nullable=False)
    repo: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accent: Mapped[str | None] = mapped_column(Text)  # small icon/accent hint for the switcher
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)

    @property
    def full_name(self) -> str:
        return f"{self.org}/{self.repo}"


class Workspace(Base):
    """A PM's private decision loop against one Product -- the isolation boundary.

    Every hosted-store table that used to implicitly mean "the repo" (Questions,
    Outcomes, Sessions, NewsItem, Settings) is scoped to a workspace_id. Two PMs can
    share a Product (same repo) while each keeps a fully separate Workspace: separate
    Questions, Outcomes, Policies, watchlist. `account_id` is a hardcoded single-row
    default until real multi-tenant auth (Phase 5); this table exists now so that
    later phase doesn't require a data migration.
    """

    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("slug", name="uq_workspaces_slug"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)  # url-safe, unique per account
    nickname: Mapped[str | None] = mapped_column(Text)  # optional per-PM override of display_name
    lens_weights: Mapped[str | None] = mapped_column(Text)  # JSON object, None = use config defaults
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)

    @property
    def lens_weights_dict(self) -> dict[str, Any]:
        return json.loads(self.lens_weights or "{}")


class Member(Base):
    """A human PM. Real identity attaches at Phase 5 auth via `external_subject`;
    until then every account has exactly one stub Member (see products.py backfill).
    """

    __tablename__ = "members"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    external_subject: Mapped[str | None] = mapped_column(Text)  # dormant until Phase 5 auth
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class Membership(Base):
    """A Member's attachment to a Product (§3: membership attaches at the Product level).

    role ships with no behaviour behind it yet -- one TEXT column now beats a
    migration later. Do not build an RBAC layer on top of it (build-spec §7).
    """

    __tablename__ = "memberships"

    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="member")  # 'owner' | 'member'
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    type: Mapped[str] = mapped_column(Text, nullable=False)  # issue|policy|document|meeting|question
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    github_ref: Mapped[str | None] = mapped_column(Text)  # only for type='issue' after push
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # durable-outcome lifecycle
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
