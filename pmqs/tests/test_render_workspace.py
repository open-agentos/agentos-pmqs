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
    assert "tab-chart" not in out        # Impacts tab removed for now (unfinished)


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


def test_meeting_draft_offers_calendar_field_and_export_receipt(db):
    # Wave 3: meetings get an optional calendar-link input; the receipt offers export.
    sess = repository.open_session(db, topic="wave3 wiring")
    out = render_workspace(sess, [], [], [], None)
    assert "Calendar link (optional)" in out
    assert "calendar_link" in out
    assert "export_url" in out
    assert "Download .md" in out


def test_wrapup_and_close_wiring(db):
    # Wave 4: the war room has a Wrap up affordance that suggests an outcome and offers
    # close-with-reason (legible absence).
    sess = repository.open_session(db, topic="wave4 wiring")
    out = render_workspace(sess, [], [], [], None)
    assert "⤶ Wrap up" in out
    assert 'id="wrapup-panel"' in out
    assert "function pmqsWrapUp" in out
    assert "function pmqsCloseRoom" in out
    assert "suggest-outcome" in out
    # the three close reasons are present
    for r in ("no_decision_yet", "decided_nothing_to_record", "couldnt_get_what_i_needed"):
        assert r in out


def test_async_action_client_wiring(db):
    # Interplay Wave 2: actions are async with a live log + busy indicator.
    sess = repository.open_session(db, topic="async wiring")
    out = render_workspace(sess, [], [], [], None)
    assert "function pmqsAjax" in out
    assert "X-PMQS-Ajax" in out
    assert "function pmqsBusy" in out
    assert "pmqsBusyLine" in out
    assert "War-room is thinking" in out
    assert "function pmqsRefreshTab" in out
    # message/lenses/doc no longer use the full-page form-submit helper
    assert "pmqsPost('/workspace/'+PMQS_SID+'/message'" not in out
    assert "pmqsPost('/workspace/'+PMQS_SID+'/run-lenses'" not in out


def test_draft_path_narrates_and_pane_busy(db):
    # Interplay Wave 3: draft path logs a click-to-open "ready" event; pane shows busy.
    sess = repository.open_session(db, topic="w3 wiring")
    out = render_workspace(sess, [], [], [], None)
    assert "function pmqsPaneBusy" in out
    assert "tabs-busy" in out
    assert "draft ready — review and commit" in out
    assert "pmqsPaneBusy(true)" in out


def test_assistant_bubble_renders_markdown_pm_stays_plain(db):
    # The war-room reply renders Markdown (source links clickable); PM input stays escaped.
    sess = repository.open_session(db, topic="md")
    repository.add_message(db, sess.id, role="pm", content="**not bold** <b>x</b>")
    repository.add_message(db, sess.id, role="assistant",
                           content="Per [#47](https://github.com/o/r/issues/47), **ship**.")
    out = render_workspace(sess, repository.list_messages(db, sess.id), [], [], None)
    # assistant: markdown rendered + link
    assert '<a href="https://github.com/o/r/issues/47"' in out
    assert "<strong>ship</strong>" in out
    # PM: literal, escaped — no injected tags
    assert "&lt;b&gt;x&lt;/b&gt;" in out
    assert "**not bold**" in out  # not rendered as bold for user input
