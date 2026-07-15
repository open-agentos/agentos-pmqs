from pmqs import scoring
from pmqs.config import LENS_WEIGHTS


class Q:
    def __init__(self, lens_tags, evidence, source="system", created_at=None):
        self._lens = lens_tags
        self._ev = evidence
        self.source = source
        self.created_at = created_at

    @property
    def lens_tags_list(self):
        return self._lens

    @property
    def evidence_list(self):
        return self._ev


def test_scoring_is_pure_deterministic():
    q = Q(["risk_exposure"], [{"ref": "#1"}])
    a = scoring.score_question(q)
    b = scoring.score_question(q)
    assert a == b


def test_higher_lens_weight_scores_higher():
    high = Q(["risk_exposure"], [{"ref": "#1"}])       # weight 1.0
    low = Q(["org_execution_drag"], [{"ref": "#1"}])   # weight 0.5
    assert scoring.score_question(high)[0] > scoring.score_question(low)[0]


def test_saved_and_proposed_use_same_formula():
    # Identical inputs -> identical score regardless of status (status isn't an input).
    q = Q(["quality_reliability"], [{"ref": "#1"}])
    s1, d1 = scoring.score_question(q)
    s2, d2 = scoring.score_question(q)
    assert (s1, d1) == (s2, d2)


def test_dimensions_present():
    _, dims = scoring.score_question(Q(["risk_exposure"], []))
    assert set(dims) == {"lens_weight", "evidence", "recency", "source"}


def test_pm_source_boost():
    pm = Q(["risk_exposure"], [{"ref": "#1"}], source="pm")
    sysq = Q(["risk_exposure"], [{"ref": "#1"}], source="system")
    assert scoring.score_question(pm)[0] > scoring.score_question(sysq)[0]
