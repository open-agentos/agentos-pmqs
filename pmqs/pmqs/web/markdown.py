"""markdown.py — a small, safe Markdown→HTML renderer for conversation bubbles.

The war-room reply is Markdown (bold, lists, links to sources). The frontend showed it
raw-escaped, so `**x**` and `[#47](url)` appeared literally. This renders the common
subset the model actually produces — paragraphs, bold/italic, inline + fenced code,
bullet/numbered lists, headings, and links — and nothing else.

Security: the whole input is HTML-escaped FIRST, so the only tags in the output are the
fixed safe set this module inserts (<strong>, <em>, <code>, <pre>, <a>, <ul>/<ol>/<li>,
<p>, <br>, a heading div). Links are scheme-checked (http/https/mailto/relative/anchor
only) so a `javascript:` URL renders as plain text. No dependency — deliberately a
limited renderer, not a full CommonMark parser.
"""
from __future__ import annotations

import html
import re

_SAFE_URL = re.compile(r"^(https?://|mailto:|/|#)", re.IGNORECASE)
_CB = "\x00CB{}\x00"  # fenced-code placeholder
_IC = "\x00IC{}\x00"  # inline-code placeholder


def _link(m: re.Match) -> str:
    label, url = m.group(1), m.group(2)
    if not _SAFE_URL.match(html.unescape(url).strip()):
        return m.group(0)  # unsafe scheme → leave as literal text
    return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'


def _inline(text: str) -> str:
    """Inline transforms on already-escaped text (code spans stashed out beforehand)."""
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, text)          # [label](url)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)   # **bold**
    text = re.sub(r"(?<!_)__([^_]+)__(?!_)", r"<strong>\1</strong>", text)  # __bold__
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)      # *italic*
    text = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<em>\1</em>", text)  # _italic_
    return text


def render_markdown(text: str) -> str:
    """Render a safe Markdown subset to HTML. Input is treated as untrusted."""
    if not text:
        return ""
    text = html.escape(text)  # escape EVERYTHING first — output tags are ours only

    code_blocks: list[str] = []
    def _stash_fence(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        # Blank lines around the placeholder so the block splitter treats a fence as its
        # own block (never nested inside a <p>, which is invalid HTML).
        return "\n\n" + _CB.format(len(code_blocks) - 1) + "\n\n"
    text = re.sub(r"```[^\n]*\n(.*?)```", _stash_fence, text, flags=re.DOTALL)

    inline_codes: list[str] = []
    def _stash_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return _IC.format(len(inline_codes) - 1)
    text = re.sub(r"`([^`\n]+)`", _stash_code, text)

    blocks_out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n")]
        nonblank = [ln for ln in lines if ln.strip()]
        if not nonblank:
            continue
        stripped = block.strip()
        if re.fullmatch(r"\x00CB\d+\x00", stripped):
            blocks_out.append(stripped)  # fenced code: its own block, no <p> wrapper
            continue
        if all(re.match(r"\s*[-*] ", ln) for ln in nonblank):
            items = "".join(
                f"<li>{_inline(re.sub(r'^\s*[-*] ', '', ln))}</li>" for ln in nonblank
            )
            blocks_out.append(f"<ul>{items}</ul>")
        elif all(re.match(r"\s*\d+\. ", ln) for ln in nonblank):
            items = "".join(
                f"<li>{_inline(re.sub(r'^\s*\d+\. ', '', ln))}</li>" for ln in nonblank
            )
            blocks_out.append(f"<ol>{items}</ol>")
        elif re.match(r"\s*#{1,6} ", nonblank[0]):
            txt = re.sub(r"^\s*#{1,6} ", "", nonblank[0])
            blocks_out.append(f'<div class="md-h">{_inline(txt)}</div>')
        else:
            blocks_out.append("<p>" + "<br>".join(_inline(ln) for ln in nonblank) + "</p>")

    out = "\n".join(blocks_out)
    for i, c in enumerate(inline_codes):
        out = out.replace(_IC.format(i), f"<code>{c}</code>")
    for i, c in enumerate(code_blocks):
        out = out.replace(_CB.format(i), f"<pre><code>{c}</code></pre>")
    return out
