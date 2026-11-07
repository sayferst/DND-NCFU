"""Observed source errors and role evidence must not become training approval."""

from training.gm_candidate_audit import quality_flags


def source_case(context, text):
    return {
        "source": "FIREBALL",
        "context": {"task": "narrate_confirmed_outcome", **context},
        "target": text,
    }


def test_publisher_automation_failure_does_not_confirm_a_missed_attack():
    case = source_case(
        {"confirmed_result": {"automation_results": ["Multiple Matches Found\n"]}},
        "The goblin swings wildly and misses the warrior completely.",
    )
    assert "AUTOMATION_ERROR_IS_NOT_A_CONFIRMED_OUTCOME" in quality_flags(case)


def test_source_hp_discrepancy_is_quarantined_without_guessing_a_new_value():
    actors = {
        "before": [{"name": "A", "hp": "<10/10 HP; Healthy>"}],
        "after": [{"name": "A", "hp": "<10/10 HP; Healthy>"}],
    }
    case = source_case(
        {"actors": actors, "confirmed_result": {"automation_results": ["A took 8 damage."]}},
        "The creature cries out as the blade strikes its shoulder.",
    )
    assert "SOURCE_STATE_AND_AUTOMATION_NEED_RECONCILIATION" in quality_flags(case)
    assert actors["after"][0]["hp"] == "<10/10 HP; Healthy>"


def test_production_discussion_in_prefix_requires_review_even_with_good_target():
    case = source_case(
        {"history": [{"text": "Hey, chat room, buy her a ticket home."}]},
        "You haven't had an opportunity to count the coins yet.",
    )
    assert "INPUT_CONTAINS_PRODUCTION_OR_OUT_OF_GAME_DISCUSSION" in quality_flags(case)


def test_finishes_him_off_needs_more_than_an_account_role():
    case = source_case({}, "Karli finishes him off for good.")
    assert "DEATH_NOT_ESTABLISHED_BY_AVAILABLE_SOURCE_RECEIPT" in quality_flags(case)
