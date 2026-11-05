"""Real DM targets need temporal evidence and exact source reconstruction."""

from copy import deepcopy

from training.source_gm_curation import (
    crd3_context,
    fireball_context,
    linked_dm_targets,
    text_screen,
)


def case():
    text = "The creature staggers back as the arrow strikes its shoulder."
    record = {
        "after_utterances": [text],
        "after_idxs": [10],
        "command_idxs": [3],
        "after_state_idx": 7,
        "embed_idxs": [6],
        "before_utterances": ["I fire."],
        "utterance_history": ["A movement in the doorway."],
    }
    message = {
        "index": 10,
        "status": "SOURCE_MESSAGE",
        "author_bot": False,
        "content": text + " (OOC note)",
        "role": "dungeon_master_account",
        "role_evidence": {"state_index": 7, "dm_id": "a"},
    }
    return record, [message]


def test_exact_normalization_keeps_published_text_without_manufacturing_authorship():
    record, messages = case()
    targets, reasons = linked_dm_targets(record, messages)
    assert targets[0]["target"] == record["after_utterances"][0] and not reasons
    messages[0]["content"] = "An almost similar arrow strikes the creature."
    targets, reasons = linked_dm_targets(record, messages)
    assert not targets and reasons["TEXT_SOURCE_NOT_EXACTLY_RECONSTRUCTED"] == 1


def test_non_bot_alone_is_not_dm_and_ambiguous_text_stays_unapproved():
    record, messages = case()
    messages[0]["role"] = "non_dm_account"
    assert not linked_dm_targets(record, messages)[0]
    record, messages = case()
    other = deepcopy(messages[0]) | {"index": 11}
    record["after_idxs"].append(11)
    assert not linked_dm_targets(record, messages + [other])[0]
    messages[0]["author_bot"] = None
    assert not linked_dm_targets(record, messages, require_non_bot=True)[0]
    assert linked_dm_targets(record, messages)[0][0]["message"]["author_bot"] is None


def test_future_state_or_bot_output_never_leaks_into_confirmed_result_input():
    for key in ("after_state_idx", "command_idxs", "embed_idxs"):
        record, messages = case()
        record[key] = 12 if key == "after_state_idx" else [12]
        assert not linked_dm_targets(record, messages)[0]
    record, messages = case()
    messages[0]["role_evidence"]["state_index"] = 11
    assert not linked_dm_targets(record, messages)[0]


def test_task_inputs_do_not_contain_target_future_replies_or_episode_summaries():
    record, _ = case()
    assert record["after_utterances"][0] not in str(fireball_context(record, 0))
    turns = [
        {"NAMES": ["LAURA"], "UTTERANCES": ["I ask the innkeeper for a room."]},
        {"NAMES": ["MATT"], "UTTERANCES": ["The innkeeper smiles at your request."]},
        {"NAMES": ["MATT"], "UTTERANCES": ["FUTURE_SECRET"]},
    ]
    context = crd3_context(turns, 1)
    assert "innkeeper smiles" not in str(context) and "FUTURE_SECRET" not in str(context)
    assert context["history"][0]["speaker_role"] == "player_or_group"


def test_screens_leave_violence_and_separate_unreceipted_numeric_adjudication():
    assert (
        text_screen("The wounded ogre roars and blood darkens its sleeve.", grounded=False) is None
    )
    assert text_screen("You take 25 damage from the lightning bolt.", grounded=False)
    assert text_screen("Welcome to Critical Role and thank you for watching!", grounded=True)
