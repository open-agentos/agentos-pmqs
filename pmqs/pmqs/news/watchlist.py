"""news/watchlist.py — the PM-configurable news watchlist (#92).

product-design.md specifies the watchlist as five things: industry, keywords, companies,
product names, and media sources. Settings offered one textarea of raw Brave query
strings, which is the fetcher's input format, not the PM's mental model.

This module is the translation, and it is deliberately pure: no DB, no network, no LLM.
Composition is deterministic so the PM can be shown exactly what will be searched
(render_settings previews it) rather than handing terms to a black box.
"""
from __future__ import annotations

# The four term fields. Sources are not terms -- they restrict, they don't search.
TERM_FIELDS = ("industry", "keywords", "companies", "products")
FIELDS = TERM_FIELDS + ("sources",)

# Composed queries are one Brave call each, and the key is the PM's. A watchlist that
# quietly turns into 400 calls per run is a bill, not a feature. Truncated, not rejected:
# a silent cap the PM can see beats a save that fails.
MAX_QUERIES = 24

# Brave's OR group has a practical length limit and a long one buries the term. Sources
# past this are dropped from the restriction rather than making every query useless.
MAX_SOURCES = 8


def parse_field(text: str) -> list[str]:
    """One term per line. Blank lines and surrounding space dropped; order and case kept
    (the PM typed 'OpenAI', not 'openai'). Deduped case-insensitively."""
    out: list[str] = []
    seen = set()
    for line in (text or "").splitlines():
        term = line.strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        out.append(term)
    return out


def _quote(term: str) -> str:
    """Multi-word terms are phrases. Unquoted, 'agent orchestration' matches documents
    about agents and, separately, orchestration."""
    return f'"{term}"' if " " in term and '"' not in term else term


def _site_group(sources: list[str]) -> str:
    if not sources:
        return ""
    clauses = [f"site:{s.lstrip('@').strip()}" for s in sources[:MAX_SOURCES] if s.strip()]
    if not clauses:
        return ""
    if len(clauses) == 1:
        return f" {clauses[0]}"
    return " (" + " OR ".join(clauses) + ")"


def build_queries(watchlist: dict[str, list[str]], raw_queries: list[str] | None = None) -> list[str]:
    """Compose the watchlist into Brave query strings.

    One query per term across industry/keywords/companies/products. Media sources are
    NOT queries of their own -- 'techcrunch.com' as a search term returns nothing useful
    -- so they fold into every query as a single OR'd `site:` group. That keeps the run
    at one call per term rather than terms x sources, which is what a cross product
    would cost.

    `raw_queries` are the escape hatch: passed through untouched, after the composed
    ones, so a PM who knows Brave's syntax isn't fenced in by these five boxes.
    """
    terms: list[str] = []
    seen = set()
    for field in TERM_FIELDS:
        for term in watchlist.get(field) or []:
            if term.lower() in seen:
                continue
            seen.add(term.lower())
            terms.append(term)

    group = _site_group(watchlist.get("sources") or [])
    queries = [f"{_quote(t)}{group}" for t in terms]

    for q in raw_queries or []:
        if q and q not in queries:
            queries.append(q)

    return queries[:MAX_QUERIES]
