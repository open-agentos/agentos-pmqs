"""Scope D of docs/build-spec-optional-repo-onramp.md: the create form leads with the
website + product details and demotes the GitHub repo to its own optional connector
section, rendered last.
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


def _create_form(db):
    # The switcher's one-field quick-add ALSO has a name="repo", ahead of the form, so
    # scope ordering assertions to the create form itself (from its heading onward).
    html = render_product_settings(db, None, mode="create")
    return html[html.index("Add a product"):]


def test_website_comes_before_repository(db):
    form = _create_form(db)
    assert form.index('name="website"') < form.index('name="repo"')


def test_repo_is_framed_optional(db):
    form = _create_form(db)
    assert "Connect a repository (optional)" in form
    assert "run on news alone" in form  # blank-repo is a supported, explained path


def test_repo_field_still_present_but_last(db):
    form = _create_form(db)
    # still there (just optional) -- and after display name / nickname
    assert 'name="repo"' in form
    assert form.index('name="display_name"') < form.index('name="repo"')
    assert form.index('name="nickname"') < form.index('name="repo"')


def test_edit_repo_hint_says_optional_and_no_detach(db):
    p = products.get_or_create_product(db, org="o", repo="a")
    html = render_product_settings(db, p, mode="edit")
    assert "detach" in html  # §14.2: blank-on-edit keeps the current repo (no detach)
