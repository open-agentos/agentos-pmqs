"""research.py — onboarding research pass for Add Product.

Given a product/company home page, draft the fields the PM would otherwise fill by hand:
a name, a profile, and a news watchlist. Three stages, each degrading independently so
research NEVER blocks Add Product (see docs/build-spec-product-onboarding.md):

  1. read the home page          (deterministic; stdlib html.parser, no new dependency)
  2. query the global search API  (Brave web search; same BRAVE_API_KEY as news)
  3. synthesise                   (one UI-triggered LLM pass; capped tokens)

Design mirrors news/fetch.py: PURE parsers (extract_homepage, parse_web_results) that are
unit-tested offline against fixtures, and THIN network wrappers that treat every failure
as non-fatal. Keys are resolved at call time via settings and are never logged or
returned to the client.
"""
from __future__ import annotations

import logging
import os
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"

# Token/scope budget. Research runs only on an explicit click (decision 12.2/12.5), so
# these bound a single onboarding action, not a recurring job.
_MAX_HTML_BYTES = 250_000     # stop reading a home page past a quarter-megabyte
_MAX_TEXT_CHARS = 8_000       # what reaches the LLM; the biggest token lever
_MAX_QUERIES = 3              # search calls per research pass
_SEARCH_COUNT = 5            # results per query
_MAX_TERMS = 8                # cap per watchlist field -- 40 companies is noise + a bill
_LIST_KEYS = ("industry", "keywords", "companies", "products", "sources")


# --------------------------------------------------------------- stage 1: read the page
class _HomeParser(HTMLParser):
    """Pull title, meta/og description, headings and visible text. No links, no repo
    guessing -- repo stays manual (decision 12.1)."""

    _SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.headings: list[str] = []
        self._text: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2"):
            self._in_heading = True
        elif tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            key = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2"):
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        if self._in_heading and len(self.headings) < 12:
            self.headings.append(text)
        self._text.append(text)


def extract_homepage(html: str) -> dict[str, Any]:
    """PURE: home-page HTML -> {title, description, site_name, text}. Never raises."""
    if not html:
        return {"title": "", "description": "", "site_name": "", "text": ""}
    p = _HomeParser()
    try:
        p.feed(html)
    except Exception:  # malformed markup should not sink onboarding
        pass
    meta = p.meta
    description = (meta.get("og:description") or meta.get("description")
                  or meta.get("twitter:description") or "").strip()
    site_name = (meta.get("og:site_name") or meta.get("application-name") or "").strip()
    title = (meta.get("og:title") or p.title or "").strip()
    text = " ".join(p.headings + p._text)[:_MAX_TEXT_CHARS]
    return {"title": title, "description": description, "site_name": site_name, "text": text}


def _fetch_url(url: str) -> str:
    """THIN: fetch a home page. Returns HTML text, or '' on any failure."""
    if not url:
        return ""
    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=15.0,
                          headers={"User-Agent": "PMQs-onboarding/1.0"}) as c:
            resp = c.get(url)
            resp.raise_for_status()
            raw = resp.content[:_MAX_HTML_BYTES]
            return raw.decode(resp.encoding or "utf-8", errors="ignore")
    except Exception as exc:  # network, HTTP, import, decode -- all non-fatal
        log.warning("research: home page fetch failed for %r: %s", url, exc)
        return ""


# ------------------------------------------------------------- stage 2: search the web
def parse_web_results(data: dict[str, Any]) -> list[dict[str, str]]:
    """PURE: Brave web-search JSON -> [{title, description, host}]. Skips entries w/o a URL."""
    out: list[dict[str, str]] = []
    for r in ((data.get("web") or {}).get("results") or []):
        url = (r.get("url") or "").strip()
        if not url:
            continue
        meta = r.get("meta_url") or {}
        out.append({
            "title": (r.get("title") or "").strip(),
            "description": (r.get("description") or "").strip(),
            "host": (meta.get("hostname") or urlparse(url).hostname or "").strip(),
        })
    return out


def build_search_queries(name: str, industry: str = "") -> list[str]:
    """PURE: a small fixed set of onboarding searches from what the page told us.

    Bounded hard at _MAX_QUERIES -- this is a one-off onboarding action, not the
    recurring news watchlist that can fan out per term.
    """
    name = (name or "").strip()
    if not name:
        return []
    quoted = f'"{name}"'
    queries = [quoted, f"{quoted} competitors", f"{quoted} alternatives"]
    if industry.strip():
        queries[2] = f'{quoted} {industry.strip()}'
    return queries[:_MAX_QUERIES]


def _search(query: str, api_key: str) -> list[dict[str, str]]:
    """THIN: one Brave web-search call. Returns parsed results; [] on any failure."""
    try:
        import httpx

        resp = httpx.get(
            _BRAVE_WEB_URL,
            params={"q": query, "count": _SEARCH_COUNT},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=20.0,
        )
        resp.raise_for_status()
        return parse_web_results(resp.json())
    except Exception as exc:
        log.warning("research: search failed for %r: %s", query, exc)
        return []


# ----------------------------------------------------------------- stage 3: synthesise
_SYS = (
    "You draft a product profile and a news watchlist for a product-management tool, "
    "from a home page and a few web-search results. Return ONLY a JSON object with keys: "
    "name (string), profile (2-4 sentence string: what it is, who it's for, who competes), "
    "industry (array), keywords (array), companies (array of competitors/adjacent players), "
    "products (array of competing/adjacent product names), sources (array of bare domains "
    "that cover this space). Be conservative: omit rather than guess, empty arrays are fine. "
    "No prose outside the JSON."
)


def _clean_terms(value: Any) -> list[str]:
    """Coerce an LLM array field to a deduped, capped list of clean strings."""
    from pmqs.news.watchlist import parse_field

    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(v) for v in value if isinstance(v, (str, int, float))]
    else:
        return []
    return parse_field("\n".join(items))[:_MAX_TERMS]


def _clean_domain(d: str) -> str:
    d = d.strip().lower()
    if "//" in d:
        d = urlparse(d).hostname or d
    return d.strip("/").split("/")[0].lstrip("@")


def _deterministic(homepage: dict[str, Any]) -> dict[str, Any]:
    """The floor: what we can say with no LLM at all -- name + rough profile from meta."""
    name = homepage.get("site_name") or homepage.get("title") or ""
    return {
        "name": name.strip(),
        "profile": (homepage.get("description") or "").strip(),
        "industry": [], "keywords": [], "companies": [], "products": [], "sources": [],
    }


def synthesize(homepage: dict[str, Any], snippets: list[dict[str, str]],
               *, settings_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stage 3: one LLM pass -> normalized suggestion dict. Falls back to the
    deterministic floor on any LLM/JSON failure. Never raises."""
    from pmqs import llm

    floor = _deterministic(homepage)
    if not (homepage.get("text") or homepage.get("description") or snippets):
        return floor

    user = (
        f"HOME PAGE\ntitle: {homepage.get('title','')}\n"
        f"site_name: {homepage.get('site_name','')}\n"
        f"description: {homepage.get('description','')}\n"
        f"text: {homepage.get('text','')}\n\n"
        "SEARCH RESULTS\n"
        + "\n".join(f"- {s['title']} ({s['host']}): {s['description']}" for s in snippets[:15])
    )
    max_tokens = int(os.environ.get("PMQS_RESEARCH_MAX_TOKENS", "1200"))
    try:
        raw = llm.complete_json(_SYS, user, settings_cfg=settings_cfg,
                                temperature=0.1, max_tokens=max_tokens)
    except Exception as exc:  # LlmUnavailable, JSON errors -- degrade, don't fail
        log.warning("research: synthesis failed, using deterministic floor: %s", exc)
        return floor
    if not isinstance(raw, dict):
        return floor

    out = {
        "name": (str(raw.get("name") or floor["name"])).strip(),
        "profile": (str(raw.get("profile") or floor["profile"])).strip(),
    }
    for key in _LIST_KEYS:
        out[key] = _clean_terms(raw.get(key))
    out["sources"] = [d for d in (_clean_domain(s) for s in out["sources"]) if d]
    return out


# ---------------------------------------------------------------------- orchestration
def research_product(db: Any, url: str) -> dict[str, str]:
    """Run all three stages for `url` and return the Add Product field draft.

    Values are newline-joined strings so the create form's textareas populate exactly
    as a hand-typed watchlist would. Never raises; a total failure returns empty fields
    and the PM just fills the form by hand.
    """
    from pmqs import settings

    homepage = extract_homepage(_fetch_url(url))

    snippets: list[dict[str, str]] = []
    api_key = settings.resolve_brave_key(db)
    if api_key:
        seed_name = homepage.get("site_name") or homepage.get("title") or ""
        for q in build_search_queries(seed_name):
            snippets.extend(_search(q, api_key))

    result = synthesize(homepage, snippets, settings_cfg=settings.get_llm(db))

    return {
        "name": result["name"],
        "profile": result["profile"],
        "industry": "\n".join(result["industry"]),
        "keywords": "\n".join(result["keywords"]),
        "companies": "\n".join(result["companies"]),
        "products": "\n".join(result["products"]),
        "sources": "\n".join(result["sources"]),
    }
