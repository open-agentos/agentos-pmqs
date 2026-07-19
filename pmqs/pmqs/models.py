"""models.py — ORM models matching the Phase 0.5 schema in build-spec-phase-0-1.md,
folded per docs/build-spec-shared-outcomes-plan.md §7/§8 step 2 (workspace -> product).

JSON-ish columns (lens_tags, evidence, score_dims, payload) are stored as TEXT and
serialized/deserialized via helpers to stay Postgres-swap friendly.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Text, Float, UniqueConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from pmqs.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    # Whose inbox this is. The Inbox is ALWAYS member-scoped (build-spec §4 rule 5, §5) --
    # it is the private half of the product, and this column is what keeps it private
    # once Phase 5 puts more than one member in a Product.
    author_member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
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
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    author_member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="shared")  # 'shared' | 'private'
    topic: Mapped[str | None] = mapped_column(Text)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))  # branching
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")  # open | closed
    position_doc: Mapped[str | None] = mapped_column(Text)  # JSON, generate-once (Phase 2)
    close_reason: Mapped[str | None] = mapped_column(Text)  # Wave 4: legible-absence signal
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

    `url` is globally unique rather than (product_id, url), so two products watching the
    same story dedupe against each other -- the second one silently doesn't see it.

    This is a DECISION, not an oversight (product owner, #96): duplicate stories across
    products are acceptable at MVP. SQLite can't ALTER a UNIQUE constraint in place, so
    the fix is a full table rebuild + copy, and that is not worth paying for at one user
    with two products. It becomes worth paying for when products share a news space and
    a missed story is a missed decision -- i.e. when there are peers, or many products
    per account. Revisit then; don't let it block Phase 4.
    """

    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    source_label: Mapped[str] = mapped_column(Text, nullable=False, default="")  # e.g. query or publisher
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # dedup key
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Product(Base):
    """The tenant-scoped unit (build-spec §3): Product is what peers join. Repos,
    watchlist, lens weights, and Membership all attach here — the Slack-'team/
    workspace' equivalent, not a bare repo pointer.

    Deduped by (org, repo): while there is no Org/multi-tenant boundary yet (Phase 5+
    auth), two calls to add the same repo resolve to the SAME Product row, and sharing
    across PMs is via Membership rows, not via separate Product rows. When a real Org
    boundary exists, the dedup key should widen to (org_id, org, repo) so two
    different companies tracking the same public repo get separate Product rows —
    that widening is a follow-up, not in scope here.

    Folded from the old `workspace` table (build-spec §8 step 2): `slug` (URL-safe,
    used by /w/{slug}/... routing), `nickname` (optional display override),
    `lens_weights` (JSON, Product-scoped per build-spec §5), and `archived` all used
    to live on a separate per-tenant `workspace` row; they now live directly on
    Product, since Membership is what supplies per-PM sharing, not a second row.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("org", "repo", name="uq_products_org_repo"),
        UniqueConstraint("slug", name="uq_products_slug"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    org: Mapped[str] = mapped_column(Text, nullable=False)
    repo: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accent: Mapped[str | None] = mapped_column(Text)  # small icon/accent hint for the switcher
    slug: Mapped[str | None] = mapped_column(Text)  # url-safe, unique; folded from workspace.slug
    nickname: Mapped[str | None] = mapped_column(Text)  # optional display override; folded from workspace.nickname
    lens_weights: Mapped[str | None] = mapped_column(Text)  # JSON object, None = use config defaults
    news_config: Mapped[str | None] = mapped_column(Text)  # JSON: watchlist/queries/product_profile (#96)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)

    @property
    def full_name(self) -> str:
        return f"{self.org}/{self.repo}"

    @property
    def lens_weights_dict(self) -> dict[str, Any]:
        return json.loads(self.lens_weights or "{}")

    @property
    def news_config_dict(self) -> dict[str, Any]:
        return json.loads(self.news_config or "{}")


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

    This is the actual "peers join my Product" mechanism (the Slack-workspace-invite
    equivalent) — one row per person per Product. role ships with no behaviour behind
    it yet -- one TEXT column now beats a migration later. Do not build an RBAC layer
    on top of it (build-spec §7).
    """

    __tablename__ = "memberships"

    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="member")  # 'owner' | 'member'
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)


class Outcome(Base):
    """A thing the PM produced in a war room. The compounding unit of PMQs.

    Lifecycle is carried by timestamps, not by a status enum (build-spec §7):
      active                    -> retired_at IS NULL
      superseded                -> retired_at IS NOT NULL AND superseded_by_outcome_id IS NOT NULL
      retired-without-replacement -> retired_at IS NOT NULL AND superseded_by_outcome_id IS NULL
    No CHECK constraints, so there is nothing to migrate when a fourth state shows up.

    NOTE — deviation from build-spec §7, deliberate: the spec's target state lists
    promoted_at/retired_at as TIMESTAMP, but every other timestamp in this schema is an
    ISO-8601 string in a TEXT column (see created_at). The doc was written from a
    description of the schema rather than the code; the code wins (§0), so these are
    TEXT for consistency and Postgres-swap parity with their neighbours.

    There is deliberately NO `visibility` column here (§7): an Outcome's visibility has
    one source of truth -- its Session -- plus the `promoted_at` exception. Resolve it
    as "shared if its session is shared, or if promoted_at IS NOT NULL"; do not
    denormalise a copy onto this row, it will drift out of sync with its room.
    """

    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    author_member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
    type: Mapped[str] = mapped_column(Text, nullable=False)  # issue|policy|document|meeting|question
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    github_ref: Mapped[str | None] = mapped_column(Text)  # only for type='issue' after push
    promoted_at: Mapped[str | None] = mapped_column(Text)  # §4 rule 3: private room -> Product ledger, one-way
    retired_at: Mapped[str | None] = mapped_column(Text)  # the active predicate: active == retired_at IS NULL
    superseded_by_outcome_id: Mapped[str | None] = mapped_column(ForeignKey("outcomes.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_now)

    @hybrid_property
    def active(self) -> bool:
        """Derived, never stored. The `active` BOOLEAN column that used to back this was
        dropped in favour of retired_at (build-spec §7: "Active is retired_at IS NULL") --
        see db._migrate_outcome_active_to_retired_at. Read-only by design: there is no
        setter, so `o.active = False` now raises rather than quietly writing a second
        source of truth. Retire via repository.deactivate_outcome().
        """
        return self.retired_at is None

    @active.inplace.expression
    @classmethod
    def _active_expression(cls):
        # Class-level form, so `select(Outcome).where(Outcome.active.is_(True))` still
        # compiles to the retired_at predicate instead of silently breaking.
        return cls.retired_at.is_(None)
