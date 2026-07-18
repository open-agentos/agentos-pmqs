"""Onboarding research: pure parsers offline, every degradation path, endpoint shape.

Mirrors news/test_news_fetch's discipline: the parsers are tested against fixtures with
no network; the network/LLM wrappers are exercised only through monkeypatched stand-ins.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pmqs import research
from pmqs.api.app import app
from pmqs.db import Base, get_session


# ----------------------------------------------------------------- stage 1 (pure)
_HTML = """
<html><head>
  <title>Acme — the widget platform</title>
  <meta name="description" content="Acme builds widgets for teams.">
  <meta property="og:site_name" content="Acme">
  <meta property="og:description" content="The widget platform for modern teams.">
  <style>.x{color:red}</style>
</head><body>
  <script>var tracking = 1;</script>
  <h1>Widgets, done right</h1>
  <p>Acme helps you ship widgets faster.</p>
</body></html>
"""


def test_extract_homepage_pulls_meta_and_text():
    hp = research.extract_homepage(_HTML)
    assert hp["site_name"] == "Acme"
    # og:description preferred over name=description
    assert hp["description"] == "The widget platform for modern teams."
    assert "Widgets, done right" in hp["text"]
    assert "Acme helps you ship widgets faster." in hp["text"]
    # script/style contents are not in the visible text
    assert "tracking" not in hp["text"]
    assert "color:red" not in hp["text"]


def test_extract_homepage_empty_is_safe():
    assert research.extract_homepage("") == {
        "title": "", "description": "", "site_name": "", "text": ""}


def test_extract_homepage_survives_malformed_markup():
    hp = research.extract_homepage("<title>Broken<h1>no close")
    assert isinstance(hp["text"], str)


# ----------------------------------------------------------------- stage 2 (pure)
_BRAVE = {
    "web": {"results": [
        {"title": "Acme vs Widgetco", "url": "https://blog.example.com/x",
         "description": "A comparison.", "meta_url": {"hostname": "blog.example.com"}},
        {"title": "no url dropped", "description": "skip me"},
        {"title": "Widgetco", "url": "https://widgetco.io/", "description": "rival"},
    ]}
}


def test_parse_web_results_shapes_and_skips():
    rows = research.parse_web_results(_BRAVE)
    assert len(rows) == 2  # the url-less entry is skipped
    assert rows[0] == {"title": "Acme vs Widgetco", "description": "A comparison.",
                       "host": "blog.example.com"}
    assert rows[1]["host"] == "widgetco.io"  # derived from url when meta_url absent


def test_parse_web_results_empty():
    assert research.parse_web_results({}) == []


def test_build_search_queries():
    qs = research.build_search_queries("Acme")
    assert qs == ['"Acme"', '"Acme" competitors', '"Acme" alternatives']
    assert research.build_search_queries("") == []
    assert len(research.build_search_queries("Acme", industry="widgets")) == 3


# ----------------------------------------------------------------- stage 3 (synthesis)
def test_synthesize_falls_back_when_llm_unavailable(monkeypatch):
    import pmqs.llm as llm

    def boom(*a, **k):
        raise llm.LlmUnavailable("no llm")

    monkeypatch.setattr(llm, "complete_json", boom)
    hp = {"title": "Acme", "description": "Widgets for teams.", "site_name": "Acme", "text": "x"}
    out = research.synthesize(hp, [])
    assert out["name"] == "Acme"
    assert out["profile"] == "Widgets for teams."
    assert out["companies"] == []  # no LLM -> no enrichment, but a valid floor


def test_synthesize_empty_input_skips_llm():
    # nothing to work from -> deterministic floor, no LLM call attempted
    out = research.synthesize({"title": "", "description": "", "site_name": "", "text": ""}, [])
    assert out["name"] == "" and out["companies"] == []


def test_synthesize_normalizes_llm_output(monkeypatch):
    import pmqs.llm as llm

    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "name": "Acme",
        "profile": "The widget platform.",
        "industry": ["widgets"],
        "keywords": "team tools\nteam tools",           # string + dupe
        "companies": ["Widgetco", "Widgetco", "Gizmo"],  # dupe collapsed
        "sources": ["https://techcrunch.com/tag/x", "  Widgetco.io "],  # cleaned to domains
        "products": [],
    })
    out = research.synthesize({"text": "x"}, [{"title": "t", "host": "h", "description": "d"}])
    assert out["name"] == "Acme"
    assert out["keywords"] == ["team tools"]
    assert out["companies"] == ["Widgetco", "Gizmo"]
    assert out["sources"] == ["techcrunch.com", "widgetco.io"]


def test_clean_terms_caps_length(monkeypatch):
    import pmqs.llm as llm
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "name": "A", "profile": "p", "companies": [f"c{i}" for i in range(40)]})
    out = research.synthesize({"text": "x"}, [])
    assert len(out["companies"]) == research._MAX_TERMS


# ----------------------------------------------------------------- orchestration
def test_research_product_joins_lists_and_never_touches_network(monkeypatch):
    # stub every boundary: no fetch, no search key, canned synthesis
    monkeypatch.setattr(research, "_fetch_url", lambda url: _HTML)
    from pmqs import settings
    monkeypatch.setattr(settings, "resolve_brave_key", lambda db: "")  # no search
    monkeypatch.setattr(settings, "get_llm", lambda db: {})
    import pmqs.llm as llm
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "name": "Acme", "profile": "p", "industry": ["widgets"],
        "companies": ["Widgetco"], "keywords": [], "products": [], "sources": []})

    out = research.research_product(db=None, url="https://acme.example")
    assert out["name"] == "Acme"
    assert out["industry"] == "widgets"
    assert out["companies"] == "Widgetco"
    assert set(out) == {"name", "profile", "industry", "keywords",
                        "companies", "products", "sources"}


# ----------------------------------------------------------------- endpoint
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
        yield c
    app.dependency_overrides.clear()


def test_research_endpoint_requires_url(client):
    assert client.post("/products/research", json={}).status_code == 400


def test_research_endpoint_returns_fields(client, monkeypatch):
    monkeypatch.setattr(research, "research_product",
                        lambda db, url: {"name": "Acme", "profile": "p", "industry": "widgets",
                                         "keywords": "", "companies": "Widgetco",
                                         "products": "", "sources": ""})
    r = client.post("/products/research", json={"url": "acme.example"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Acme" and body["companies"] == "Widgetco"


def test_research_endpoint_creates_nothing(client, monkeypatch):
    from sqlalchemy import select
    from pmqs.models import Product

    monkeypatch.setattr(research, "research_product", lambda db, url: {"name": "X"})
    client.post("/products/research", json={"url": "https://x.example"})

    sess = next(app.dependency_overrides[get_session]())
    assert sess.scalars(select(Product)).first() is None
