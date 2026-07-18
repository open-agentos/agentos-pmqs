"""Add Product persists the whole config on create (not just repo/nickname).

The create form renders the full watchlist/profile/lens set (#99) and the onboarding
research pass pre-populates it. Before this, POST /products dropped everything but
repo/nickname. These tests pin that the create path now saves it -- and, critically,
that resolving to an EXISTING product does NOT clobber that product's config.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import products
from pmqs.api.app import app
from pmqs.db import Base, get_session


@pytest.fixture
def client(monkeypatch):
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


_FULL = {
    "repo": "open-agentos/agentos",
    "display_name": "AgentOS",
    "wl_industry": "agent orchestration",
    "wl_keywords": "AI agents\nagent runtime",
    "wl_companies": "Anthropic\nOpenAI",
    "wl_products": "Claude Code",
    "wl_sources": "techcrunch.com",
    "news_queries": "site:example.com foo",
    "product_profile": "A GitHub-primitives agent orchestration system.",
    "website": "https://agentos.example",
    "lens_risk_exposure": "0.9",
}


def test_create_persists_watchlist_and_profile(client):
    client.post("/products", data=_FULL, follow_redirects=False)
    s = client._session_factory()
    p = products.get_product_by_slug(s, "agentos")
    cfg = products.get_news_config(s, p)
    s.close()
    assert cfg["watchlist"]["industry"] == ["agent orchestration"]
    assert cfg["watchlist"]["keywords"] == ["AI agents", "agent runtime"]
    assert cfg["watchlist"]["companies"] == ["Anthropic", "OpenAI"]
    assert cfg["watchlist"]["sources"] == ["techcrunch.com"]
    assert cfg["queries"] == ["site:example.com foo"]
    assert cfg["product_profile"].startswith("A GitHub-primitives")
    assert cfg["website"] == "https://agentos.example"


def test_researched_name_becomes_display_name(client):
    """Decision 12.3: the researched name lands in display_name, not nickname."""
    client.post("/products", data=_FULL, follow_redirects=False)
    s = client._session_factory()
    p = products.get_product_by_slug(s, "agentos")
    s.close()
    assert p.display_name == "AgentOS"
    assert p.nickname is None  # research does not touch nickname


def test_create_persists_lens_override(client):
    client.post("/products", data=_FULL, follow_redirects=False)
    s = client._session_factory()
    p = products.get_product_by_slug(s, "agentos")
    weights = products.weights_for(s, p.id)
    s.close()
    assert weights["risk_exposure"] == 0.9


def test_resolving_existing_product_does_not_clobber_config(client):
    """Two PMs, same repo -> one Product. The second add must not overwrite the first's
    watchlist/profile with its own (possibly empty) form."""
    s = client._session_factory()
    first = products.get_or_create_product(s, org="open-agentos", repo="agentos",
                                           display_name="AgentOS")
    products.set_news_config(s, first, watchlist={"industry": ["keep me"]},
                             product_profile="original profile", website="https://kept")
    s.close()

    # A second add of the SAME repo, carrying a different (would-be-clobbering) form.
    client.post("/products", data={"repo": "open-agentos/agentos",
                                   "display_name": "Someone Elses Name",
                                   "wl_industry": "should not win",
                                   "product_profile": "should not win either"},
                follow_redirects=False)

    s = client._session_factory()
    p = products.get_product_by_slug(s, first.slug)
    cfg = products.get_news_config(s, p)
    s.close()
    assert cfg["watchlist"]["industry"] == ["keep me"]
    assert cfg["product_profile"] == "original profile"
    assert cfg["website"] == "https://kept"
    assert p.display_name == "AgentOS"  # display_name not overwritten on resolve


def test_edit_save_preserves_website(client):
    """The edit form has no website field yet -- saving it must not wipe the stored one."""
    s = client._session_factory()
    p = products.get_or_create_product(s, org="o", repo="a", display_name="A")
    products.set_news_config(s, p, watchlist={"industry": ["x"]}, website="https://keep.me")
    slug = p.slug
    s.close()

    client.post(f"/w/{slug}/settings", data={"display_name": "A", "wl_industry": "y"},
                follow_redirects=False)

    s = client._session_factory()
    p = products.get_product_by_slug(s, slug)
    cfg = products.get_news_config(s, p)
    s.close()
    assert cfg["website"] == "https://keep.me"
    assert cfg["watchlist"]["industry"] == ["y"]
