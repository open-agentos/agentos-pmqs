"""members.py — Member/Membership repository (Shared Outcomes build-spec, §7/§8 step 1).

Member is the human-PM identity; Membership attaches a Member to a Product with a
role. No auth yet (Phase 5): every account resolves to one stub Member, created on
first use and reused thereafter. Kept in its own module, same pattern as products.py.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from pmqs.models import Member, Membership, Product

DEFAULT_MEMBER_DISPLAY_NAME = "You"


def get_or_create_default_member(db: OrmSession) -> Member:
    """Return the account's single stub Member, creating it if this is the first call.

    Single-tenant until Phase 5 auth attaches real identities via
    `external_subject` — see build-spec §7 backfill note.
    """
    existing = db.scalars(select(Member)).first()
    if existing is not None:
        return existing
    member = Member(display_name=DEFAULT_MEMBER_DISPLAY_NAME)
    db.add(member)
    db.commit()
    return member


def get_membership(db: OrmSession, *, member_id: str, product_id: str) -> Membership | None:
    return db.get(Membership, {"member_id": member_id, "product_id": product_id})


def ensure_membership(
    db: OrmSession, *, member: Member, product: Product, role: str = "owner"
) -> Membership:
    """Idempotent: returns the existing Membership row if one already exists for this
    (member, product) pair rather than raising on the composite primary key.
    """
    existing = get_membership(db, member_id=member.id, product_id=product.id)
    if existing is not None:
        return existing
    membership = Membership(member_id=member.id, product_id=product.id, role=role)
    db.add(membership)
    db.commit()
    return membership


def list_memberships(db: OrmSession, *, member_id: str) -> list[Membership]:
    return list(db.scalars(select(Membership).where(Membership.member_id == member_id)))
