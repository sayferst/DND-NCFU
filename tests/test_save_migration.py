"""Read a real v1 fixture from 4346127 without rewriting it during load."""

import json
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import Character
from rpg_vkr.storage.slots import SaveSlots

FIXTURE = Path(__file__).parent / "fixtures" / "save-v1.json"


def test_v1_load_keeps_old_unknown_command_and_dice_sequence(tmp_path):
    original = FIXTURE.read_bytes()
    path = tmp_path / "slot-1.json"
    path.write_bytes(original)
    store = SaveSlots(tmp_path)
    assert store.info(1).occupied
    restored = store.load(1)
    assert restored.character == Character()
    assert restored.turns[1].action == "проверить силу"
    assert restored.turns[1].check is None
    assert "пока не понимаю" in restored.turns[1].text
    assert restored.turns[2].roll.value == 4
    assert restored.submit("проверить силу").roll.value == 1
    assert path.read_bytes() == original


def test_explicit_save_migrates_v1_and_can_be_loaded_again(tmp_path):
    path = tmp_path / "slot-1.json"
    path.write_bytes(FIXTURE.read_bytes())
    store = SaveSlots(tmp_path)
    session = store.load(1)
    previous = session.turns
    store.save(1, session)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    reloaded = SaveSlots(tmp_path).load(1)
    assert reloaded.turns == previous
    assert reloaded.character == Character()
    assert reloaded.submit("бросить d20").roll.value == 1


def test_v2_custom_character_check_and_next_roll_round_trip(tmp_path):
    session = Session(seed=42, character=Character(name="Мира", strength=18))
    turn = session.submit("проверить силу")
    assert turn.check.modifier == 4
    assert turn.check.total == 8
    store = SaveSlots(tmp_path)
    store.save(3, session)
    restored = SaveSlots(tmp_path).load(3)
    assert restored.to_dict() == session.to_dict()
    assert restored.submit("бросить d20").roll.value == 1


@pytest.mark.parametrize("changes", [{"total": 99}, {"succeeded": True}, {"modifier": False}])
def test_changed_check_result_is_rejected(changes):
    session = Session(seed=42)
    session.submit("проверить силу")
    data = session.to_dict()
    data["turns"][0]["check"].update(changes)
    with pytest.raises(ValueError):
        Session.from_dict(data)
