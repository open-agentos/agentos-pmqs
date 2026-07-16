"""Tests for the Workspace list view (Shared Outcomes build-spec §10.1, Wave 2 item 7)."""
import os

os.environ["PMQS_LLM_MODE"] = "off"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products, repository
from pmqs.db import Base
from pmqs.models import Member


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def me(db):
    return members.get_or_create_default_member(db)


@pytest.fixture
def colleague(db, me):
    m = Member(display_name="Ada Lovelace")
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def product(db, me):
    return products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")


def _room(db, product, author, *, topic="a room", visibility="shared", created="2026-01-01T00:00:00+00:00"):
    s = repository.open_session(db, topic=topic, product_id=product.id,
                                author_member_id=author.id, visibility=visibility)
    s.created_at = created
    db.commit()
    return s


def _rows(db, product, me, **kw):
    return repository.list_workspace_rows(db, product_id=product.id, member_id=me.id, **kw)


# --- columns (§10.1) ---

def test_row_carries_name_owner_and_outcome_count(db, product, me, colleague):
    room = _room(db, product, colleague, topic="Are we losing on price?")
    repository.create_outcome(db, type="policy", payload={"text": "p"},
                              session_id=room.id, product_id=product.id)
    repository.create_outcome(db, type="document", payload={"title": "d", "body": "b"},
                              session_id=room.id, product_id=product.id)

    row = _rows(db, product, me)[0]
    assert row["name"] == "Are we losing on price?"
    assert row["owner_name"] == "Ada Lovelace"
    assert row["outcome_count"] == 2


def test_untitled_room_has_a_name(db, product, me):
    s = repository.open_session(db, topic=None, product_id=product.id, author_member_id=me.id)
    assert _rows(db, product, me)[0]["name"] == "(untitled)"


def test_room_with_no_outcomes_counts_zero(db, product, me):
    _room(db, product, me)
    assert _rows(db, product, me)[0]["outcome_count"] == 0


def test_outcome_count_is_not_inflated_by_messages(db, product, me):
    """The join multiplies rows; the count must not multiply with it."""
    room = _room(db, product, me)
    for i in range(3):
        repository.add_message(db, room.id, role="pm", content=f"m{i}")
    repository.create_outcome(db, type="policy", payload={"text": "p"},
                              session_id=room.id, product_id=product.id)

    assert _rows(db, product, me)[0]["outcome_count"] == 1


# --- last modified is derived, not stored (deviation from §10.1) ---

def test_last_modified_follows_the_newest_message(db, product, me):
    room = _room(db, product, me, created="2026-01-01T00:00:00+00:00")
    m = repository.add_message(db, room.id, role="pm", content="hello")
    m.created_at = "2026-06-01T00:00:00+00:00"
    db.commit()

    assert _rows(db, product, me)[0]["last_modified"] == "2026-06-01T00:00:00+00:00"


def test_last_modified_follows_the_newest_outcome(db, product, me):
    room = _room(db, product, me, created="2026-01-01T00:00:00+00:00")
    o = repository.create_outcome(db, type="policy", payload={"text": "p"},
                                  session_id=room.id, product_id=product.id)
    o.created_at = "2026-05-01T00:00:00+00:00"
    db.commit()

    assert _rows(db, product, me)[0]["last_modified"] == "2026-05-01T00:00:00+00:00"


def test_last_modified_falls_back_to_created_at(db, product, me):
    _room(db, product, me, created="2026-02-02T00:00:00+00:00")
    assert _rows(db, product, me)[0]["last_modified"] == "2026-02-02T00:00:00+00:00"


def test_default_sort_is_last_modified_descending(db, product, me):
    old = _room(db, product, me, topic="old", created="2026-01-01T00:00:00+00:00")
    new = _room(db, product, me, topic="new", created="2026-01-02T00:00:00+00:00")
    m = repository.add_message(db, old.id, role="pm", content="revived")
    m.created_at = "2026-09-09T00:00:00+00:00"
    db.commit()

    # `old` was created first but touched last, so it leads.
    assert [r["name"] for r in _rows(db, product, me)] == ["old", "new"]


# --- privacy (§10.1) ---

def test_another_members_private_room_is_absent(db, product, me, colleague):
    """"Like an unshared Doc, simply absent from everyone else's list." Absence IS the
    feature -- a redacted row would still tell you a colleague is working on something,
    which is exactly what private is for."""
    _room(db, product, colleague, topic="their secret", visibility="private")
    _room(db, product, colleague, topic="their shared room")

    names = [r["name"] for r in _rows(db, product, me)]
    assert names == ["their shared room"]


def test_my_own_private_room_is_present_and_marked(db, product, me):
    _room(db, product, me, topic="my secret", visibility="private")
    row = _rows(db, product, me)[0]
    assert row["name"] == "my secret"
    assert row["is_private"] is True


def test_list_does_not_cross_the_product_boundary(db, me):
    a = products.get_or_create_product(db, org="open-agentos", repo="agentos-pmqs")
    b = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    _room(db, a, me, topic="mine here")
    _room(db, b, me, topic="other product")

    assert [r["name"] for r in repository.list_workspace_rows(
        db, product_id=a.id, member_id=me.id)] == ["mine here"]


# --- filter chips (§10.1) ---

def test_filter_any_owner_shows_shared_rooms_from_everyone(db, product, me, colleague):
    _room(db, product, me, topic="mine")
    _room(db, product, colleague, topic="theirs")

    assert {r["name"] for r in _rows(db, product, me, owner="any")} == {"mine", "theirs"}


def test_filter_owned_by_me(db, product, me, colleague):
    _room(db, product, me, topic="mine")
    _room(db, product, colleague, topic="theirs")

    assert [r["name"] for r in _rows(db, product, me, owner="mine")] == ["mine"]


def test_filter_not_owned_by_me(db, product, me, colleague):
    _room(db, product, me, topic="mine")
    _room(db, product, colleague, topic="theirs")

    assert [r["name"] for r in _rows(db, product, me, owner="not_mine")] == ["theirs"]


def test_not_owned_by_me_still_hides_their_private_rooms(db, product, me, colleague):
    """The filter narrows the list; it must never widen it past §4."""
    _room(db, product, colleague, topic="their secret", visibility="private")
    _room(db, product, colleague, topic="theirs")

    assert [r["name"] for r in _rows(db, product, me, owner="not_mine")] == ["theirs"]


def test_owned_by_me_includes_my_private_rooms(db, product, me):
    _room(db, product, me, topic="my secret", visibility="private")
    assert [r["name"] for r in _rows(db, product, me, owner="mine")] == ["my secret"]


def test_ownerless_room_is_not_mine(db, product, me):
    """Rooms predating the authorship backfill have no author. They must not silently
    become "mine" -- author_member_id != me would drop NULLs on a bare comparison."""
    s = repository.open_session(db, topic="orphan", product_id=product.id)
    s.author_member_id = None
    db.commit()

    assert [r["name"] for r in _rows(db, product, me, owner="not_mine")] == ["orphan"]
    assert _rows(db, product, me, owner="mine") == []


# --- rendering + route (§10.1) ---
# These matter more than usual here: render.py splices into app.html via regex anchored
# on its markup, and TEMPLATE-CONTRACT.md is explicit that no test asserts on that markup
# and CI will not catch breakage. These assert on the spliced output.

def test_rendered_list_shows_name_owner_count_and_date(db, product, me, colleague):
    from pmqs.web.render import render_workspace_list

    room = _room(db, product, colleague, topic="Are we losing on price?",
                 created="2026-04-04T00:00:00+00:00")
    o = repository.create_outcome(db, type="policy", payload={"text": "p"},
                                  session_id=room.id, product_id=product.id)
    # the outcome is what last-modified derives from, so pin it too
    o.created_at = "2026-04-04T09:00:00+00:00"
    db.commit()

    out = render_workspace_list(db, _rows(db, product, me))
    assert "Are we losing on price?" in out
    assert "Ada Lovelace" in out
    assert "1 outcome" in out
    assert "2026-04-04" in out


def test_rendered_list_replaces_the_placeholder(db, product, me):
    """If the anchor ever stops matching, the page renders the fixture silently -- which
    is exactly the failure mode TEMPLATE-CONTRACT.md warns about."""
    from pmqs.web.render import render_workspace_list

    _room(db, product, me, topic="a real room")
    out = render_workspace_list(db, _rows(db, product, me))
    assert "a real room" in out
    assert "No workspaces yet." not in out


def test_empty_list_renders_the_empty_state(db, product, me):
    from pmqs.web.render import render_workspace_list

    out = render_workspace_list(db, [])
    assert "No workspaces yet." in out


def test_rendered_names_are_escaped(db, product, me):
    from pmqs.web.render import render_workspace_list

    _room(db, product, me, topic="<script>alert(1)</script>")
    out = render_workspace_list(db, _rows(db, product, me))
    assert "<script>alert(1)</script>" not in out


def test_active_filter_chip_is_marked(db, product, me):
    from pmqs.web.render import render_workspace_list

    out = render_workspace_list(db, [], owner="mine")
    assert '<div class="filter-pill active" data-ws-owner="mine">' in out
    assert '<div class="filter-pill" data-ws-owner="any">' in out


def test_the_workspace_nav_opens_the_list_not_a_room(db, product, me):
    """§10.1: "The Workspace nav item currently opens the current room. It must open a
    list."."""
    from pmqs.web.render import render_workspace_list

    out = render_workspace_list(db, [])
    assert "/workspaces'" in out
    assert 'data-nav="workspace"' in out


def test_private_row_says_private_without_a_colour(db, product, me):
    """§10.1: hue carries state, not identity. "private" is a word, not a hue."""
    from pmqs.web.render import render_workspace_list

    _room(db, product, me, topic="my secret", visibility="private")
    out = render_workspace_list(db, _rows(db, product, me))
    assert "· private" in out
