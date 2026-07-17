"""#109 — thread-line treatment on the conversation pane.

The contract's §4 rule is the one worth pinning here: render.py emits .msg, .msg-label,
.msg-body and .sys-bubble, and the template must keep a CSS rule for each or real
messages render unstyled — a failure that looks like a design bug rather than a wiring
bug, and which no other test would catch.
"""
import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository
from pmqs.web.render import render_workspace, _initials

TEMPLATE = Path(__file__).parent.parent / "pmqs" / "web" / "templates" / "app.html"
BG_MAIN = "#12181c"


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    chans = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _token(name: str) -> str:
    m = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})" % re.escape(name),
                  TEMPLATE.read_text(encoding="utf-8"))
    assert m, f"token --{name} not found in :root"
    return m.group(1)


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def convo(db):
    q = repository.create_question(db, title="Ship or wait?", source="system")
    sess = repository.open_session(db, topic="Ship or wait", question_id=q.id)
    repository.add_message(db, sess.id, role="system", content="SYSMSG this has sat 9 days")
    repository.add_message(db, sess.id, role="pm", content="PMMSG I lean toward shipping")
    repository.add_message(db, sess.id, role="assistant", content="ASSTMSG what breaks?")
    return render_workspace(sess, repository.list_messages(db, sess.id), [], [], None)


def test_conversation_renders_real_messages(convo):
    for probe in ("SYSMSG this has sat 9 days", "PMMSG I lean toward shipping",
                  "ASSTMSG what breaks?"):
        assert probe in convo
    assert "What's actually at risk if we mitigate" not in convo


def test_every_message_gets_an_avatar(convo):
    assert convo.count('class="msg-avatar"') == 3


def test_initials():
    assert _initials("You") == "Y"
    assert _initials("System") == "S"
    assert _initials("War-room") == "WR", "hyphen must split, not be swallowed"
    assert _initials("") == "?"


def _rendered_classes(html_src: str) -> set:
    out = set()
    for m in re.finditer(r'class="([^"]+)"', html_src):
        out.update(m.group(1).split())
    return out


def test_contract_section_4_classes_all_keep_a_css_rule(convo):
    """render.py emits these; the template must style each or real data renders naked."""
    css = TEMPLATE.read_text(encoding="utf-8")
    rendered = _rendered_classes(convo)
    for cls in ("msg", "msg-label", "msg-body", "sys-bubble", "pm-bubble",
                "msg-avatar", "msg-col"):
        assert re.search(r"\.%s[{ ,:.]" % re.escape(cls), css), \
            f".{cls} is emitted by render.py but has no CSS rule"
        assert cls in rendered, f".{cls} has a CSS rule but is not emitted"


def test_connector_is_suppressed_on_the_last_message():
    css = TEMPLATE.read_text(encoding="utf-8")
    assert ".msg::before{" in css, "the connector rule is missing"
    assert ".msg:last-child::before{display:none;}" in css


def test_connector_uses_border_default():
    css = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"\.msg::before\{[^}]*background:var\(--([a-z-]+)\)", css)
    assert m and m.group(1) == "border-default"


def test_avatar_initials_are_legible_on_their_fill():
    """The spec proposed --accent-teal-fg on --accent-teal, which measures 2.45:1.
    --accent-teal is documented FILL ONLY, so the initials need a real text token."""
    css = TEMPLATE.read_text(encoding="utf-8")
    for rule in (r"\.msg\.system \.msg-avatar\{background:var\(--([a-z-]+)\);color:var\(--([a-z-]+)\)",
                 r"\.msg\.pm \.msg-avatar\{background:var\(--([a-z-]+)\);color:var\(--([a-z-]+)\)"):
        m = re.search(rule, css)
        assert m, f"avatar rule missing: {rule}"
        ratio = contrast(_token(m.group(2)), _token(m.group(1)))
        assert ratio >= 4.5, (
            f"--{m.group(2)} on --{m.group(1)} is {ratio:.2f}:1; avatar initials are text"
        )


def test_the_specced_avatar_pairing_really_would_have_failed():
    assert contrast(_token("accent-teal-fg"), _token("accent-teal")) < 3.0


def test_convo_anchor_classes_and_order_survive(convo):
    """_CONVO_RE matches .convo-scroll … .convo-input; both names and their order are
    load-bearing."""
    assert 'class="convo-scroll"' in convo
    assert 'class="convo-input"' in convo
    assert convo.index('class="convo-scroll"') < convo.index('class="convo-input"')
