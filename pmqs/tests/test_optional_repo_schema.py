"""Scope A of docs/build-spec-optional-repo-onramp.md: GitHub stops being a Product's
identity. org/repo go nullable, a website-only product still gets a stable slug, and an
existing NOT NULL DB is rebuilt in place.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from pmqs import products
from pmqs.db import Base, _migrate_products_relax_repo_notnull
from pmqs.models import Product


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


# --- website-only products are first-class -------------------------------------------

def test_create_without_repo_persists_null_org_repo(db):
    p = products.get_or_create_product(db, website="https://acme.example", display_name="Acme")
    assert p.org is None and p.repo is None
    assert p.has_repo is False
    assert p.full_name == ""  # not "None/None" -- callers build `gh --repo` off this
    assert p.slug  # got a real slug
    assert p.display_name == "Acme"


def test_two_repo_less_products_coexist(db):
    a = products.get_or_create_product(db, website="https://a.example", display_name="A")
    b = products.get_or_create_product(db, website="https://b.example", display_name="B")
    # No (org, repo) key to resolve on -> two distinct rows, distinct slugs. SQLite
    # treats (NULL, NULL) as distinct so the unique constraint doesn't collapse them.
    assert a.id != b.id
    assert a.slug != b.slug


def test_repo_backed_create_and_dedup_unchanged(db):
    first = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    again = products.get_or_create_product(db, org="open-agentos", repo="agentos")
    assert first.id == again.id  # (org, repo) still resolves to the same Product
    assert first.full_name == "open-agentos/agentos"
    assert first.has_repo is True


def test_repo_less_and_repo_backed_dont_dedup_together(db):
    site = products.get_or_create_product(db, website="https://x.example", display_name="X")
    repo = products.get_or_create_product(db, org="o", repo="x")
    assert site.id != repo.id


# --- slug fallback chain -------------------------------------------------------------

def test_slug_prefers_nickname_then_name_then_host(db):
    p = products.get_or_create_product(db, website="https://www.Acme-Corp.io/pricing",
                                       display_name="Acme")
    assert p.slug == "acme"  # display name wins over host
    q = products.get_or_create_product(db, website="https://www.Widgets.io/x")
    assert q.slug == "widgets-io"  # falls through to the bare host when no name given


def test_host_extractor():
    assert products._host("https://www.acme.io/pricing?x=1") == "acme.io"
    assert products._host("http://Foo.Example") == "Foo.Example"
    assert products._host("") == ""
    assert products._host(None) == ""


def test_display_name_never_empty_for_website_only(db):
    p = products.get_or_create_product(db, website="https://solo.example")
    assert p.display_name  # non-empty -- falls back to the host


# --- the relax-NOT-NULL migration ---------------------------------------------------

def _old_schema_engine():
    """A products table shaped like the pre-refactor DB: org/repo NOT NULL."""
    e = create_engine("sqlite:///:memory:", future=True)
    with e.begin() as conn:
        conn.execute(text(
            "CREATE TABLE products ("
            " id TEXT PRIMARY KEY, org TEXT NOT NULL, repo TEXT NOT NULL,"
            " display_name TEXT NOT NULL DEFAULT '', accent TEXT, slug TEXT, nickname TEXT,"
            " lens_weights TEXT, news_config TEXT, archived BOOLEAN DEFAULT 0,"
            " created_at TEXT NOT NULL,"
            " CONSTRAINT uq_products_org_repo UNIQUE (org, repo),"
            " CONSTRAINT uq_products_slug UNIQUE (slug))"
        ))
        conn.execute(text(
            "INSERT INTO products (id, org, repo, display_name, slug, created_at)"
            " VALUES ('p1', 'open-agentos', 'agentos-pmqs', 'agentos-pmqs', 'agentos-pmqs', '2026-01-01')"
        ))
    return e


def _notnull(conn, col):
    info = conn.execute(text("PRAGMA table_info(products)")).fetchall()
    return {r[1]: r[3] for r in info}[col]


def test_migration_relaxes_not_null_and_keeps_data():
    e = _old_schema_engine()
    with e.begin() as conn:
        assert _notnull(conn, "org") == 1 and _notnull(conn, "repo") == 1  # precondition
        _migrate_products_relax_repo_notnull(conn)
        assert _notnull(conn, "org") == 0 and _notnull(conn, "repo") == 0  # relaxed
        # existing row survived intact
        row = conn.execute(text("SELECT org, repo, display_name FROM products WHERE id='p1'")).fetchone()
        assert row == ("open-agentos", "agentos-pmqs", "agentos-pmqs")
        # and a website-only row now inserts where before it would have failed NOT NULL
        conn.execute(text(
            "INSERT INTO products (id, org, repo, display_name, slug, created_at)"
            " VALUES ('p2', NULL, NULL, 'Acme', 'acme', '2026-02-02')"
        ))
        got = conn.execute(text("SELECT org, repo FROM products WHERE id='p2'")).fetchone()
        assert got == (None, None)


def test_migration_is_idempotent():
    e = _old_schema_engine()
    with e.begin() as conn:
        _migrate_products_relax_repo_notnull(conn)
        _migrate_products_relax_repo_notnull(conn)  # second pass is a no-op
        assert _notnull(conn, "org") == 0
        assert conn.execute(text("SELECT COUNT(*) FROM products")).scalar() == 1


def test_migration_no_op_on_fresh_schema():
    # A model-built (already nullable) table must be left untouched.
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    with e.begin() as conn:
        _migrate_products_relax_repo_notnull(conn)
        assert _notnull(conn, "org") == 0
