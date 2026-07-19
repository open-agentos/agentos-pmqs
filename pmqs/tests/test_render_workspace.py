from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from pmqs.db import Base
from pmqs import repository
from pmqs.web.render import render_workspace


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    yield s
    s.close()


def test_render_workspace_splices_real_data(db):
    q = repository.create_question(db, title="Ship or wait?", source="system",
                                   evidence=[{"type": "issue", "ref": "#47", "url": "http://x/47"}])
    sess = repository.open_session(db, topic="Ship or wait on #47", question_id=q.id)
    repository.add_message(db, sess.id, role="pm", content="I lean toward shipping")
    repository.add_message(db, sess.id, role="assistant", content="What breaks if you do?")
    proposed = [repository.create_question(db, title="Proposed: verify drift earlier?", source="system")]
    evidence = q.evidence_list
    doc = {"summary": "S", "what_your_vote_means": "W", "background_impact": "B",
           "argument_for": "F", "rebuttal_for": "RF", "argument_against": "A", "rebuttal_against": "RA"}

    out = render_workspace(sess, repository.list_messages(db, sess.id), evidence, proposed, doc)

    # Real conversation content present
    assert "I lean toward shipping" in out
    assert "What breaks if you do?" in out
    # Title spliced
    assert "Ship or wait on #47" in out
    # Evidence tab has the real ref
    assert "#47" in out
    # Proposed tab has the real proposed question
    assert "verify drift earlier" in out
    # Position doc section present
    assert "Voter-Guide format" in out
    # Other views preserved (no regression)
    assert 'id="view-inbox"' in out
    assert 'id="view-outcomes"' in out
    # Mockup fixture message should be gone from the convo (replaced)
    assert "This has sat for 9 days" not in out


def test_render_workspace_empty_states(db):
    sess = repository.open_session(db, topic="empty session")
    out = render_workspace(sess, [], [], [], None)
    assert "Run lenses" in out           # proposed empty-state hint
    assert "No evidence bound yet" in out
    assert "Not generated yet" in out    # position doc empty-state
    assert 'id="view-inbox"' in out


def test_outcome_bar_uses_inline_fetch_receipt(db):
    # Wave 1: the war room must POST outcomes via fetch and render a receipt inline,
    # never the old full-page form submit that dumped the PM on raw JSON.
    sess = repository.open_session(db, topic="receipt wiring")
    out = render_workspace(sess, [], [], [], None)
    assert "function addOutcome" in out
    assert "pmqsOutcomeReceipt" in out
    assert "/outcome'," in out and "fetch(" in out
    # The old form-submit path for outcomes is gone.
    assert "pmqsPost('/workspace/'+PMQS_SID+'/outcome'" not in out


def test_draft_tab_and_draft_first_wiring(db):
    # Wave 2: the war room has an editable Draft tab and the outcome buttons are
    # draft-first (draft → edit → commit), not one-shot.
    sess = repository.open_session(db, topic="draft wiring")
    out = render_workspace(sess, [], [], [], None)
    assert 'id="tab-draft"' in out and 'id="draft-body"' in out
    assert 'data-tab="draft"' in out
    assert "function pmqsDraft" in out
    assert "function pmqsRenderDraft" in out
    assert "function pmqsCommitOutcome" in out
    assert "function addOutcome(type){ pmqsDraft(type); }" in out
