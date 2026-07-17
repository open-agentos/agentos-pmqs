"""Product.lens_weights actually reaches scoring (#97).

The column existed, was settable at product creation, and was read by nobody:
score_question(question, cfg_weights=None) offered the seam and all four call sites
ignored it, so every product scored against the global config.LENS_WEIGHTS.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pmqs import config, products, repository, scoring
from pmqs.db import Base


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_unset_weights_are_exactly_the_defaults(db):
    """Unchanged behaviour for every product that hasn't tuned anything."""
    p = products.get_or_create_product(db, org="o", repo="a")
    assert products.weights_for(db, p.id) == config.LENS_WEIGHTS


def test_no_product_gives_the_defaults(db):
    assert products.weights_for(db, None) == config.LENS_WEIGHTS


def test_unknown_product_id_gives_the_defaults_rather_than_raising(db):
    assert products.weights_for(db, "nope") == config.LENS_WEIGHTS


def test_a_partial_override_does_not_zero_the_other_lenses(db):
    """The merge is the point: tuning one lens must not silently drop the other seven."""
    p = products.get_or_create_product(db, org="o", repo="a",
                                       lens_weights={"unit_economics": 0.95})
    w = products.weights_for(db, p.id)
    assert w["unit_economics"] == 0.95
    assert w["risk_exposure"] == config.LENS_WEIGHTS["risk_exposure"]
    assert set(w) == set(config.LENS_WEIGHTS)


def test_junk_weight_falls_back_rather_than_crashing_scoring(db):
    p = products.get_or_create_product(db, org="o", repo="a",
                                       lens_weights={"unit_economics": "banana"})
    assert products.weights_for(db, p.id)["unit_economics"] == config.LENS_WEIGHTS["unit_economics"]


def test_weights_do_not_leak_between_products(db):
    a = products.get_or_create_product(db, org="o", repo="a", lens_weights={"risk_exposure": 0.1})
    b = products.get_or_create_product(db, org="o", repo="b")
    assert products.weights_for(db, a.id)["risk_exposure"] == 0.1
    assert products.weights_for(db, b.id)["risk_exposure"] == config.LENS_WEIGHTS["risk_exposure"]


def test_two_products_score_the_same_question_differently(db):
    """The whole point: the product changes what ranks."""
    a = products.get_or_create_product(db, org="o", repo="a",
                                       lens_weights={"unit_economics": 1.0})
    b = products.get_or_create_product(db, org="o", repo="b",
                                       lens_weights={"unit_economics": 0.1})
    q = repository.create_question(db, title="Margin question", source="pm",
                                   lens_tags=["unit_economics"])
    score_a, dims_a = scoring.score_question(q, products.weights_for(db, a.id))
    score_b, dims_b = scoring.score_question(q, products.weights_for(db, b.id))
    assert dims_a["lens_weight"] == 1.0
    assert dims_b["lens_weight"] == 0.1
    assert score_a > score_b


def test_quick_add_scores_against_the_products_weights(db):
    """api/inbox.py's call site, end to end."""
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from pmqs.api.app import app
    from pmqs.db import get_session

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
        s = TS()
        p = products.get_or_create_product(s, org="o", repo="a",
                                           lens_weights={"risk_exposure": 1.0})
        slug = p.slug
        s.close()
        c.post(f"/w/{slug}/quick-add", data={"title": "Is this risky?", "lens": "risk_exposure"})
        s = TS()
        q = repository.list_questions(s)[0]
        assert q.score_dims_dict["lens_weight"] == 1.0
        s.close()
    app.dependency_overrides.clear()
