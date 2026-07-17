"""Product Settings is its own view, reached from the switcher (#98).

The line: /settings is yours (identity block), /w/{slug}/settings is the product's
(switcher). Before this, /w/{slug}/settings rendered ACCOUNT settings behind a product
prefix that scoped nothing.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import config, members, products
from pmqs.api.app import app
from pmqs.db import Base, get_session
from pmqs.web.render import render_product_settings, render_settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def client():
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

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        c._session_factory = TS
        yield c
    app.dependency_overrides.clear()


from fastapi.testclient import TestClient  # noqa: E402


def _product(db, repo="a", **kw):
    return products.get_or_create_product(db, org="o", repo=repo, **kw)


# --- the split ---

def test_the_two_surfaces_do_not_overlap(db):
    p = _product(db)
    account = render_settings(db)
    product = render_product_settings(db, p, workspace_slug=p.slug)

    # Yours.
    assert 'name="display_name"' in account and 'name="api_key_ref"' in account
    assert 'name="char_budget"' in account
    assert 'name="wl_industry"' not in account
    assert 'name="lens_risk_exposure"' not in account

    # The product's.
    assert 'name="wl_industry"' in product and 'name="product_profile"' in product
    assert 'name="lens_risk_exposure"' in product
    assert 'name="api_key_ref"' not in product
    assert 'name="char_budget"' not in product


def test_product_settings_renders_in_the_shell(db):
    p = _product(db)
    html = render_product_settings(db, p, workspace_slug=p.slug)
    assert '<div id="rail">' in html
    assert 'id="view-settings"' in html
    assert "showView('settings')" in html
    assert "Fixture content" not in html


def test_the_page_says_the_url_does_not_move_when_you_rename(db):
    """Renaming must not move URLs out from under links to them. Say so; don't let the
    PM guess."""
    p = _product(db)
    html = render_product_settings(db, p, workspace_slug=p.slug)
    assert f"/w/{p.slug}/" in html
    assert "move when you rename" in html  # apostrophe is escaped on the way out


def test_every_lens_has_a_label(db):
    assert set(config.LENS_LABELS) == set(config.LENS_WEIGHTS)
    p = _product(db)
    html = render_product_settings(db, p, workspace_slug=p.slug)
    import html as html_mod

    for label in config.LENS_LABELS.values():
        assert html_mod.escape(label) in html


def test_members_are_listed_read_only(db):
    p = _product(db)
    m = members.get_or_create_default_member(db)
    members.set_display_name(db, member_id=m.id, display_name="Ada L")
    members.ensure_membership(db, member=m, product=p, role="owner")
    html = render_product_settings(db, p, workspace_slug=p.slug)
    assert "Ada L" in html and "owner" in html


def test_member_names_are_escaped(db):
    p = _product(db)
    m = members.get_or_create_default_member(db)
    members.set_display_name(db, member_id=m.id, display_name="<script>x</script>")
    members.ensure_membership(db, member=m, product=p, role="owner")
    html = render_product_settings(db, p, workspace_slug=p.slug)
    assert "<script>x</script>" not in html


def test_two_products_show_their_own_config(db):
    a = _product(db, "a")
    b = _product(db, "b")
    products.set_news_config(db, a, watchlist={"companies": ["Anthropic"]})
    products.set_news_config(db, b, watchlist={"companies": ["Figma"]})
    ha = render_product_settings(db, a, workspace_slug=a.slug)
    hb = render_product_settings(db, b, workspace_slug=b.slug)
    assert ">Anthropic</textarea>" in ha and ">Figma</textarea>" not in ha
    assert ">Figma</textarea>" in hb and ">Anthropic</textarea>" not in hb


# --- routes ---

def test_unknown_slug_404s(client):
    assert client.get("/w/nope/settings").status_code == 404


def test_saving_identity_round_trips(client):
    s = client._session_factory()
    slug = _product(s).slug
    s.close()
    r = client.post(f"/w/{slug}/settings", data={
        "display_name": "Renamed", "nickname": "nick", "repo": "o/a"}, follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    p = products.get_product_by_slug(s, slug)
    assert p.display_name == "Renamed" and p.nickname == "nick"
    assert p.slug == slug  # the URL did NOT move
    s.close()


def test_lens_weights_round_trip(client):
    s = client._session_factory()
    slug = _product(s).slug
    s.close()
    client.post(f"/w/{slug}/settings", data={"lens_risk_exposure": "0.25"})
    s = client._session_factory()
    p = products.get_product_by_slug(s, slug)
    assert products.weights_for(s, p.id)["risk_exposure"] == 0.25
    # A partial override leaves the other seven at their defaults.
    assert products.weights_for(s, p.id)["unit_economics"] == config.LENS_WEIGHTS["unit_economics"]
    s.close()


def test_a_junk_lens_weight_keeps_the_default_rather_than_zeroing_the_lens(client):
    s = client._session_factory()
    slug = _product(s).slug
    s.close()
    client.post(f"/w/{slug}/settings", data={"lens_risk_exposure": "banana"})
    s = client._session_factory()
    assert products.weights_for(s, products.get_product_by_slug(s, slug).id)["risk_exposure"] == \
        config.LENS_WEIGHTS["risk_exposure"]
    s.close()


def test_a_malformed_repo_says_so_instead_of_500ing(client):
    s = client._session_factory()
    slug = _product(s).slug
    s.close()
    r = client.post(f"/w/{slug}/settings", data={"repo": "not-a-repo-ref"}, follow_redirects=False)
    assert r.status_code == 303
    assert "product_error=invalid_repo" in r.headers["location"]


def test_archive_hides_it_from_the_switcher_without_deleting(client):
    s = client._session_factory()
    slug = _product(s).slug
    s.close()
    r = client.post(f"/w/{slug}/settings/archive", follow_redirects=False)
    assert r.status_code == 303
    s = client._session_factory()
    assert products.list_products(s) == []
    assert products.get_product_by_slug(s, slug) is not None  # still there
    s.close()
