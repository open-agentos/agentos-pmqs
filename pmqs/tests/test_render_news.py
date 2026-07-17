from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository, settings
from pmqs.web.render import render_inbox, render_workspace, render_settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_news_card_has_from_news_pill(db):
    q = repository.create_question(
        db, title="Rival shipped agent orchestration", source="news",
        evidence=[{"type": "news", "source": "pub.example", "title": "Rival ships", "url": "http://x/1", "date": "2026-07-14", "hedged": True}],
    )
    html = render_inbox([q])
    assert "From news" in html
    assert "Rival shipped agent orchestration" in html


def test_news_evidence_rendered_hedged_in_workspace(db):
    q = repository.create_question(
        db, title="Rival move", source="news",
        evidence=[{"type": "news", "source": "TechCrunch", "title": "Rival raises $50M", "url": "http://tc/1", "date": "2026-07-14", "hedged": True}],
    )
    sess = repository.open_session(db, topic="Rival move", question_id=q.id)
    html = render_workspace(sess, repository.list_messages(db, sess.id), q.evidence_list, [], None)
    assert "TechCrunch" in html
    assert "reportedly" in html
    assert "Rival raises $50M" in html


def test_settings_has_news_section_and_masks_key(db):
    settings.set_news_config(db, api_key_raw="SECRETBRAVE", queries=["ai agents"],
                             product_profile="PMQs profile")
    html = render_settings(db)
    assert ">News</h2>" in html
    assert "Fetch news now" in html
    assert "ai agents" in html
    assert "PMQs profile" in html
    assert "SECRETBRAVE" not in html  # masked, never echoed


def test_inbox_has_settings_nav_wiring(db):
    html = render_inbox([])
    assert "pmqs-settings-nav" in html
    assert "/settings" in html
