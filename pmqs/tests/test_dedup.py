from pmqs.dedup import dedup


def test_near_duplicates_merge_to_one():
    cands = [
        {"title": "Stale issue #42 needs attention now", "description": "a",
         "lens_tags": ["quality_reliability"], "evidence": [{"ref": "#42"}], "source": "system"},
        {"title": "Issue #42 is stale and needs attention", "description": "b",
         "lens_tags": ["quality_reliability"], "evidence": [{"ref": "#42"}], "source": "system"},
    ]
    out = dedup(cands)
    assert len(out) == 1
    assert "[dedup]" in out[0]["description"]


def test_distinct_questions_both_survive():
    cands = [
        {"title": "Ship mitigation for data-loss bug", "description": "a",
         "lens_tags": ["risk_exposure"], "evidence": [{"ref": "#47"}], "source": "system"},
        {"title": "Reduce error-loop spend with retry budget", "description": "b",
         "lens_tags": ["unit_economics"], "evidence": [{"ref": "#88"}], "source": "system"},
    ]
    out = dedup(cands)
    assert len(out) == 2


def test_shared_evidence_ref_merges():
    cands = [
        {"title": "Completely different words here alpha", "description": "a",
         "lens_tags": ["risk_exposure"], "evidence": [{"ref": "#47"}], "source": "system"},
        {"title": "Nothing alike beta gamma delta", "description": "b",
         "lens_tags": ["quality_reliability"], "evidence": [{"ref": "#47"}], "source": "system"},
    ]
    out = dedup(cands)
    assert len(out) == 1
    # lens tags unioned
    assert set(out[0]["lens_tags"]) == {"risk_exposure", "quality_reliability"}
