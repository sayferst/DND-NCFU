"""Routing, reproducibility and validation of the saved session."""

import pytest

from rpg_vkr.application import Session


@pytest.mark.parametrize("action", ["бросить d20", "  БРОСИТЬ   D20! ", "бросить д20"])
def test_roll_is_calculated_and_recorded(action):
    session = Session(seed=42)
    turn = session.submit(action)
    assert turn.speaker == "Кубик"
    assert turn.text == "d20 → 4"
    assert turn.roll.value == 4
    assert turn.roll.index == 1
    assert session.turns == (turn,)


@pytest.mark.parametrize("action", ["осмотреться", "бросить d20 + 100", "не бросить d20"])
def test_non_dice_action_does_not_consume_a_roll(action):
    session = Session(seed=42)
    assert session.submit(action).roll is None
    assert session.submit("бросить d20").roll.value == 4


def test_reloaded_history_preserves_text_and_the_next_roll():
    session = Session(seed=42)
    session.submit("помочь")
    session.submit("бросить d20")
    restored = Session.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()
    assert restored.submit("бросить d20") == session.submit("бросить d20")
    assert restored.turns[-1].roll.value == 1


def test_blank_action_does_not_modify_session():
    session = Session(seed=42)
    with pytest.raises(ValueError):
        session.submit("   ")
    assert not session.turns


@pytest.mark.parametrize("seed", [None, True, -1, "42", 2**128])
def test_invalid_saved_seed_is_rejected(seed):
    data = Session(seed=42).to_dict()
    data["seed"] = seed
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_tampered_dice_history_is_rejected():
    session = Session(seed=42)
    session.submit("бросить d20")
    data = session.to_dict()
    data["turns"][0]["roll"]["value"] = 20
    data["turns"][0]["text"] = "d20 → 20"
    with pytest.raises(ValueError, match="Dice history"):
        Session.from_dict(data)


@pytest.mark.parametrize(
    ("command", "ability", "modifier"),
    [
        ("проверить силу", "strength", 2),
        ("проверить ловкость", "dexterity", 1),
        ("проверить телосложение", "constitution", 1),
        ("проверить интеллект", "intelligence", 0),
        ("проверить мудрость", "wisdom", 2),
        ("проверить харизму", "charisma", -1),
    ],
)
def test_check_commands_use_character_and_shared_d20(command, ability, modifier):
    session = Session(seed=42)
    turn = session.submit(command.upper())
    assert turn.roll.value == 4
    assert turn.check.ability == ability
    assert turn.check.modifier == modifier
    assert turn.check.total == 4 + modifier
    assert turn.check.difficulty == 10
    assert turn.speaker == "Правила"
    assert session.submit("бросить d20").roll.value == 1
