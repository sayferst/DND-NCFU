"""Draft cancellation, atomic batches, stale revisions and request idempotency."""

import pytest
from test_campaign_skills import trained

from rpg_vkr.domain.d20_progression import D20Progress
from rpg_vkr.domain.skill_allocation import commit, preview


def test_draft_is_pure_and_commit_is_atomic_and_idempotent():
    p = D20Progress()
    draft = preview(p, {"athletics": 2, "knowledge": 1})
    assert p.skill_points == 13 and draft.skill_points == 9
    result = commit(p, {"athletics": 2, "knowledge": 1}, "first", p)
    assert result.skill_points == draft.skill_points
    assert commit(result, {"knowledge": 1, "athletics": 2}, "first", p) == result
    restored = D20Progress.from_dict(result.to_dict())
    assert commit(restored, {"athletics": 2, "knowledge": 1}, "first", p) == restored
    with pytest.raises(ValueError, match="другого распределения"):
        commit(result, {"athletics": 1}, "first", result)


def test_failure_does_not_spend_partial_batch_and_stale_snapshot_rejected():
    session = trained()
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.commit_skill_allocation(
            {"repair": 2, "knowledge": 5}, "invalid", session.d20_progress
        )
    assert session.to_dict() == before
    old = session.d20_progress
    session.train_skill("knowledge")
    after = session.to_dict()
    with pytest.raises(ValueError, match="изменилось"):
        session.commit_skill_allocation({"repair": 1}, "stale", old)
    assert session.to_dict() == after


def test_ui_cancel_does_not_change_campaign_and_apply_commits_once(window):
    window._session = trained()
    window._refresh_character()
    window.skill_choice.setCurrentIndex(window.skill_choice.findData("repair"))
    before = window._session.to_dict()
    window.train_skill_button.click()
    assert window._session.to_dict() == before
    window.skill_cancel_button.click()
    assert window._session.to_dict() == before and not window.skill_apply_button.isEnabled()
    window.train_skill_button.click()
    window.skill_apply_button.click()
    assert window._session.d20_progress.rank("repair") == 1
    assert not window.skill_apply_button.isEnabled()


def test_draft_cannot_be_applied_to_another_campaign(window):
    window._session = trained()
    window._refresh_character()
    window.skill_choice.setCurrentIndex(window.skill_choice.findData("repair"))
    window.train_skill_button.click()
    window._session = trained()
    window._refresh_character()
    assert not window.skill_apply_button.isEnabled()
    assert window._session.d20_progress.rank("repair") == 0
