"""Add Product is Product Settings in create mode (#99) — plus the four live bugs.

The one-field quick-add in the switcher is the right fast path and survives. What was
broken was everything after the click.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import members, products
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs.models import Member
from pmqs.web.render import render_product_settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def client(monkeypatch):
    # seed_workspace reads live substrate; keep the tests offline and deterministic.
    import pmqs.api.products as api_products

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _override():
        s = TS()
        try:
            yield s
        finally:
            s.close()

    import pmqs.pipeline as pipeline
    monkeypatch.setattr(pipeline, "seed_workspace", lambda db, product: [])
    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        c._session_factory = TS
        yield c
    app.dependency_overrides.clear()


# --- the same view, one mode apart ---

def test_create_mode_renders_the_same_fields_as_edit(db):
    """Everything you'd set when adding is everything you'd edit later."""
    create = render_product_settings(db, None, mode="create")
    p = products.get_or_create_product(db, org="o", repo="a")
    edit = render_product_settings(db, p, workspace_slug=p.slug, mode="edit")
    for field in ("wl_industry", "wl_keywords", "wl_companies", "wl_products",
                  "wl_sources", "product_profile", "nickname", "lens_risk_exposure"):
        assert f'name="{field}"' in create, field
        assert f'name="{field}"' in edit, field


def test_create_mode_posts_to_products_and_says_add(db):
    html = render_product_settings(db, None, mode="create")
    assert 'action="/products"' in html
    assert "Add product" in html
    assert 'name="repo"' in html


def test_create_mode_has_no_members_or_archive(db):
    """There's nothing to archive and nobody to list before the Product exists."""
    html = render_product_settings(db, None, mode="create")
    assert ">Members</h2>" not in html
    assert ">Archive</h2>" not in html


def test_create_page_renders_without_a_product(client):
    assert client.get("/products/new").status_code == 200


# --- bug 1: it lands on the product you just added ---

def test_add_lands_on_the_new_products_settings(client):
    r = client.post("/products", data={"repo": "open-agentos/agentos"}, follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    p = products.get_product_by_slug(s, "agentos")
    s.close()
    assert p is not None
    assert r.headers["location"] == f"/w/{p.slug}/settings?added=1"


def test_add_does_not_dump_you_in_another_products_inbox(client):
    """The old behaviour: redirect to "/", i.e. the default product."""
    s = client._session_factory()
    products.get_or_create_product(s, org="o", repo="first")
    s.close()
    r = client.post("/products", data={"repo": "open-agentos/agentos"}, follow_redirects=False)
    assert r.headers["location"] != "/"
    assert "agentos" in r.headers["location"]


# --- bug 2: nickname is wired ---

def test_nickname_is_wired_through(client):
    r = client.post("/products", data={"repo": "open-agentos/agentos", "nickname": "the substrate"},
                    follow_redirects=False)
    s = client._session_factory()
    p = products.list_products(s)[0]
    assert p.nickname == "the substrate"
    assert p.slug == "the-substrate"  # the nickname sets the URL at creation
    s.close()
    assert r.headers["location"] == f"/w/{p.slug}/settings?added=1"


# --- bug 3: a malformed ref says so ---

def test_malformed_repo_redirects_to_the_form_with_an_error(client):
    r = client.post("/products", data={"repo": "not-a-ref"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/products/new?product_error=invalid_repo"


def test_the_error_is_actually_rendered(client):
    """It has been redirected to since #53 and rendered by nothing."""
    html = client.get("/products/new?product_error=invalid_repo").text
    assert "org/repo reference" in html


def test_the_added_confirmation_is_rendered(client):
    client.post("/products", data={"repo": "open-agentos/agentos"})
    html = client.get("/w/agentos/settings?added=1").text
    assert "Product added" in html


def test_an_unknown_flag_renders_nothing_rather_than_leaking_it(client):
    """The flash is an allowlist lookup, not an echo -- the value never reaches the
    page, so an attacker-supplied one has nothing to reach it with."""
    html = client.get("/products/new?product_error=%3Cimg+src%3Dx+onerror%3Dalert(1)%3E").text
    assert "onerror" not in html
    assert "org/repo reference" not in html  # no flash section at all


# --- bug 4: Membership ---

def test_add_creates_a_membership(client):
    """Nothing on this path called ensure_membership. Only db.py's backfill ever made a
    Membership row, so every product added through the UI had none."""
    client.post("/products", data={"repo": "open-agentos/agentos"})
    s = client._session_factory()
    p = products.list_products(s)[0]
    people = members.list_product_members(s, product_id=p.id)
    assert len(people) == 1
    assert people[0][1] == "owner"
    s.close()


def test_adding_a_repo_someone_already_added_joins_the_same_product(client):
    """The entire point of get_or_create_product: two PMs, same repo, ONE Product."""
    client.post("/products", data={"repo": "open-agentos/agentos"})
    client.post("/products", data={"repo": "open-agentos/agentos"})
    s = client._session_factory()
    assert len(products.list_products(s)) == 1
    p = products.list_products(s)[0]
    assert len(members.list_product_members(s, product_id=p.id)) == 1  # no duplicate row
    s.close()


def test_membership_is_created_on_resolve_not_only_on_create(client):
    """A second PM adding an existing repo is exactly when Membership matters most."""
    s = client._session_factory()
    p = products.get_or_create_product(s, org="open-agentos", repo="agentos")  # exists, no membership
    assert members.list_product_members(s, product_id=p.id) == []
    s.close()

    client.post("/products", data={"repo": "open-agentos/agentos"})

    s = client._session_factory()
    assert len(members.list_product_members(s, product_id=p.id)) == 1
    s.close()
