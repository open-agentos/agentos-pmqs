from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_create_and_dedup_by_url(db):
    a = repository.create_news_item(db, url="http://x/1", title="A", source_label="q")
    assert a is not None
    # same URL again → None (dedup)
    b = repository.create_news_item(db, url="http://x/1", title="A dup")
    assert b is None
    assert len(repository.list_news_items(db)) == 1


def test_unprocessed_filter_and_mark(db):
    i1 = repository.create_news_item(db, url="http://x/1", title="A")
    i2 = repository.create_news_item(db, url="http://x/2", title="B")
    assert len(repository.list_news_items(db, unprocessed_only=True)) == 2
    repository.mark_news_processed(db, [i1.id])
    unproc = repository.list_news_items(db, unprocessed_only=True)
    assert [i.id for i in unproc] == [i2.id]


def test_news_item_defaults_unprocessed(db):
    i = repository.create_news_item(db, url="http://x/1", title="A")
    assert i.processed is False
