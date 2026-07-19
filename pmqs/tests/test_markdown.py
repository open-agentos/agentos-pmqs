"""test_markdown.py — the conversation Markdown renderer (format + safety)."""
from pmqs.web.markdown import render_markdown as r


def test_bold_italic_code():
    assert "<strong>x</strong>" in r("**x**")
    assert "<strong>x</strong>" in r("__x__")
    assert "<em>x</em>" in r("*x*")
    assert "<code>pytest</code>" in r("`pytest`")


def test_links_to_sources():
    out = r("see [#47](https://github.com/o/r/issues/47)")
    assert '<a href="https://github.com/o/r/issues/47"' in out
    assert 'target="_blank"' in out and 'rel="noopener"' in out
    assert ">#47</a>" in out


def test_lists():
    assert r("- a\n- b").startswith("<ul>") and "<li>a</li>" in r("- a\n- b")
    assert r("1. a\n2. b").startswith("<ol>") and "<li>a</li>" in r("1. a\n2. b")


def test_paragraphs_and_linebreaks():
    out = r("one\ntwo\n\nthree")
    assert "<p>one<br>two</p>" in out
    assert "<p>three</p>" in out


def test_fenced_code_is_its_own_block():
    out = r("before\n```\ncode\n```\nafter")
    assert "<pre><code>code" in out
    assert "<p><pre>" not in out  # never nested inside a paragraph


# --- safety ---

def test_script_is_escaped():
    assert "<script>" not in r("<script>alert(1)</script>")
    assert "&lt;script&gt;" in r("<script>alert(1)</script>")


def test_raw_html_is_escaped():
    assert "<img" not in r("<img src=x onerror=alert(1)>")


def test_javascript_url_is_not_linked():
    out = r("[x](javascript:alert(1))")
    assert "<a " not in out          # unsafe scheme → left as literal text
    assert "javascript:alert(1)" not in out or "href" not in out


def test_empty_is_empty():
    assert r("") == ""
    assert r(None) == ""
