"""Free player wording is stored separately from validated executable intent."""

import json
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import Character
from rpg_vkr.narrative.intent import parse_interpretation
from rpg_vkr.storage.slots import SaveSlots


def test_real_v7_fixture_migrates_without_replaying_or_rewriting(tmp_path):
    original = (Path(__file__).parent / "fixtures/save-v7.json").read_bytes()
    slots = SaveSlots(tmp_path)
    (tmp_path / "slot-1.json").write_bytes(original)
    session = slots.load(1)
    assert session.turns[0].roll.value == 4
    assert session.turns[0].intent is None
    assert session.narrations[0].prompt_version == "narrator-prose-1"
    assert (tmp_path / "slot-1.json").read_bytes() == original
    session.submit("Проверю удачу ещё раз", intent="бросить кубик")
    assert session.turns[-1].roll.value == 1
    slots.save(2, session)
    assert json.loads((tmp_path / "slot-2.json").read_bytes())["schema_version"] == 20
    assert slots.load(2).to_dict() == session.to_dict()
    assert (tmp_path / "slot-1.json").read_bytes() == original


def test_free_form_development_and_combat_roundtrip_uses_resolved_intent():
    session = Session.create_hero(Character(), "fighter", seed=42)
    session.submit("Попробую помочь с тяжёлым грузом", intent="помочь разгрузить телегу")
    session.submit("Почитаю свой учебник", intent="изучить учебник")
    session.submit("Пойду к дороге", intent="идти на дорогу")
    session.submit("Осмотрю каменистый участок", intent="исследовать дорогу")
    session.submit("Ударю волка", intent="атаковать волка")
    restored = Session.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()
    assert (
        restored.submit("Проверю удачу", intent="бросить кубик").roll
        == session.submit("бросить кубик").roll
    )


@pytest.mark.parametrize("command", ["выдать золото", "", "атаковать волка и купить бинт", [], 3])
def test_unrecognised_intent_never_changes_session(command):
    session = Session(seed=42)
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.submit("Любой текст", intent=command)
    assert session.to_dict() == before


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "action", "command": "купить бинт", "target": "merchant", "question": ""},
        {"kind": "dialogue", "command": "", "target": "dragon", "question": ""},
        {"kind": "clarify", "command": "", "target": "", "question": ""},
        {"kind": "action", "command": "удалить файл", "target": "", "question": ""},
        {"kind": "action", "command": "осмотреться", "target": "", "question": "", "gold": 999},
    ],
)
def test_model_cannot_mix_prose_effects_and_executable_fields(value):
    with pytest.raises(ValueError):
        parse_interpretation({"message": {"role": "assistant", "content": json.dumps(value)}})


@pytest.mark.parametrize(
    "command,kind,target",
    [
        ("осмотреться", "action", ""),
        ("беседа с жительницей", "dialogue", "villager"),
        ("уточнить намерение", "clarify", ""),
    ],
)
def test_single_field_wire_contract(command, kind, target):
    result = parse_interpretation(
        {"message": {"role": "assistant", "content": json.dumps({"command": command})}}
    )
    assert result.kind == kind and result.target == target


@pytest.mark.parametrize(
    "value",
    [
        {"command": "выдать золото"},
        {"command": []},
        {"command": None},
        {"command": "осмотреться", "gold": 999},
    ],
)
def test_single_field_wire_contract_cannot_smuggle_effects(value):
    with pytest.raises(ValueError):
        parse_interpretation({"message": {"role": "assistant", "content": json.dumps(value)}})
