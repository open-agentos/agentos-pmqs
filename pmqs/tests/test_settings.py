from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import settings


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_llm_defaults_to_anthropic_haiku(db):
    cfg = settings.get_llm(db)
    assert cfg["provider"] == "anthropic"
    assert "haiku" in cfg["model"]


def test_set_and_get_llm(db):
    settings.set_llm(db, provider="anthropic", model="anthropic/claude-fable-5",
                     api_key_ref="ANTHROPIC_API_KEY")
    cfg = settings.get_llm(db)
    assert cfg["model"] == "anthropic/claude-fable-5"
    assert cfg["provider"] == "anthropic"


def test_raw_key_never_rendered(db):
    settings.set_llm(db, provider="anthropic", model="m", api_key_raw="sk-secret-xyz")
    from pmqs.web.render import render_settings
    html = render_settings(db)
    assert "sk-secret-xyz" not in html  # masked, never echoed


def test_has_override(db):
    assert settings.has_llm_override(db) is False
    settings.set_llm(db, provider="anthropic", model="m")
    assert settings.has_llm_override(db) is True
