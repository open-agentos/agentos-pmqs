"""#110 — rank badge on Inbox rows."""
import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository
from pmqs.web.render import render_inbox, question_card_html

TEMPLATE = Path(__file__).parent.parent / "pmqs" / "web" / "templates" / "app.html"
# .card's background — the surface the badge actually sits on. Read from the
# template so this follows a palette change instead of pinning a stale hex.


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
    assert m, f"token --{name} not found"
    return m.group(1)


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


@pytest.fixture
def questions(db):
    for i in range(4):
        repository.create_question(db, title=f"Question number {i}", source="system")
    return repository.list_questions(db)


def _badges(out: str) -> list:
    return re.findall(r'<span class="rank-badge(?: top)?">(\d+)</span>', out)


def test_ranks_are_sequential_from_one(questions):
    assert _badges(render_inbox(questions)) == ["1", "2", "3", "4"]


def test_rank_is_list_position_not_a_recomputed_score(db):
    """Rank must follow the caller's ordering. Give the FIRST row the LOWEST score: if
    anything re-sorts or recomputes, rank 1 stops landing on the row the caller put
    first."""
    a = repository.create_question(db, title="Low score, listed first", source="system")
    b = repository.create_question(db, title="High score, listed second", source="system")
    a.score, b.score = 0.10, 0.99
    db.commit()
    out = render_inbox([a, b])
    first = out.index("Low score, listed first")
    second = out.index("High score, listed second")
    assert first < second
    assert '<span class="rank-badge top">1</span>Low score, listed first' in out
    assert '<span class="rank-badge top">2</span>High score, listed second' in out


def test_only_the_top_two_are_accented(questions):
    out = render_inbox(questions)
    assert out.count('class="rank-badge top"') == 2
    assert out.count('class="rank-badge"') == 2
    # and they are the first two
    assert '<span class="rank-badge top">1</span>' in out
    assert '<span class="rank-badge top">2</span>' in out
    assert '<span class="rank-badge">3</span>' in out


def test_badge_sits_inside_card_main_before_the_title(questions):
    out = render_inbox(questions)
    assert re.search(r'<div class="card-title"><span class="rank-badge[^"]*">1</span>', out)


def test_score_pill_survives_alongside_the_badge(db):
    """The badge is position, the pill is magnitude. Both, not either."""
    q = repository.create_question(db, title="Scored question", source="system")
    q.score = 0.87
    db.commit()
    out = render_inbox([q])
    assert "score 0.87" in out
    assert '<span class="rank-badge top">1</span>' in out


def test_scoring_model_is_untouched(db):
    """No four-level severity enum: the multi-dimensional axis stays."""
    q = repository.create_question(db, title="Q", source="pm")
    q.score = 0.5
    db.commit()
    out = render_inbox([q])
    assert "Asked by you" in out
    for enum in ("severity", ">critical<", ">high<", ">medium<", ">low<"):
        assert enum not in out.lower() or enum == "severity"


def test_rank_is_optional(db):
    """question_card_html stays usable without a rank."""
    q = repository.create_question(db, title="Unranked", source="system")
    assert "rank-badge" not in question_card_html(q)


def test_top_badge_is_not_fainter_than_the_default():
    """The spec asked for --accent-gold-dim on the top two. On --bg-active (.card's
    surface) that measures 2.43:1 against --text-muted's 2.59:1 — the emphasis token
    would be dimmer than the thing it emphasises. If someone reverts this, it fails."""
    css = TEMPLATE.read_text(encoding="utf-8")
    default = re.search(r"\.rank-badge\{[^}]*color:var\(--([a-z-]+)\)", css)
    top = re.search(r"\.rank-badge\.top\{color:var\(--([a-z-]+)\)", css)
    assert default and top
    surface = _token("bg-active")
    assert contrast(_token(top.group(1)), surface) > contrast(_token(default.group(1)), surface)

