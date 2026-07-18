"""The Add Product onramp UI: a Website field, a Research button, and the prefill JS.

Create mode is the primary onramp; edit mode gets the same controls so a product can be
re-researched. The JS targets fields by name within the form, so these tests assert the
wiring is present and points at /products/research.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs import products
from pmqs.db import Base
from pmqs.web.render import render_product_settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_create_form_has_website_and_research_button(db):
    html = render_product_settings(db, None, mode="create")
    assert 'name="website"' in html
    assert "Research this site" in html
    assert 'onclick="pmqsResearchSite(this)"' in html
    # the researched name lands in display_name (12.3), so the field must exist on create
    assert 'name="display_name"' in html


def test_research_button_does_not_submit_the_form(db):
    """type=button, or clicking Research would submit a half-empty create form."""
    html = render_product_settings(db, None, mode="create")
    assert 'type="button" onclick="pmqsResearchSite(this)"' in html


def test_prefill_js_posts_to_research_endpoint(db):
    html = render_product_settings(db, None, mode="create")
    assert "/products/research" in html
    # maps the endpoint's keys onto the form field names
    for pair in ("display_name:'name'", "product_profile:'profile'",
                 "wl_industry:'industry'", "wl_sources:'sources'"):
        assert pair in html


def test_edit_form_shows_stored_website_and_can_reresearch(db):
    p = products.get_or_create_product(db, org="o", repo="a", display_name="A")
    products.set_news_config(db, p, watchlist={"industry": ["x"]},
                             website="https://kept.example")
    html = render_product_settings(db, p, workspace_slug=p.slug, mode="edit")
    assert 'name="website"' in html
    assert "https://kept.example" in html
    assert "Research this site" in html


def test_create_form_still_posts_to_products(db):
    """The onramp additions don't change where the form submits."""
    html = render_product_settings(db, None, mode="create")
    assert 'action="/products"' in html
    assert "Add product" in html
