"""A faithful chain of new changes; no invented replay of historical commands."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.memory import WorldMemory, digest, snapshot
from rpg_vkr.domain.progression import ARCHETYPES
from rpg_vkr.domain.world import WorldState
from rpg_vkr.narrative.context import build_frame, visible_changes
from rpg_vkr.narrative.records import Narration
from rpg_vkr.storage.slots import SaveSlots


def fighter():
    return Session.create_hero(
        Character(
            name="Мира", **dict(zip(ABILITY_NAMES, ARCHETYPES["fighter"].scores, strict=True))
        ),
        "fighter",
        seed=5,
    )


def test_state_changes_capture_quest_gold_inventory_location_and_full_battle_rolls():
    session = fighter()
    for command in (
        "взять поручение",
        "идти на рынок",
        "доставить корзину",
        "идти на дорогу",
        "подкрасться к волку",
        "атаковать волка",
    ):
        session.submit(command)
    events = session.memory.events
    assert len(events) == 6
    assert {c.field: (c.before, c.after) for c in events[0].changes}["world.basket"] == (0, 1)
    assert {c.field: (c.before, c.after) for c in events[2].changes}["world.gold"] == (8, 13)
    assert events[1].location == "market"
    assert events[4].roll_indices == (1,)
    assert events[5].roll_indices == (2, 3)
    assert "Отношение" not in ";".join(visible_changes(events[5]))
    assert "Ранения: Серый волк" in ";".join(visible_changes(events[5]))
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_failed_or_informational_action_has_empty_changes_and_no_extra_rolls():
    session = Session(seed=42)
    session.submit("купить бинт")
    session.submit("осмотреться")
    assert all(not event.changes and not event.roll_indices for event in session.memory.events)
    assert session.memory.events[0].before_hash == session.memory.events[1].after_hash
    assert session.submit("бросить кубик").roll.value == 4


def test_memory_failure_rolls_back_rng_state_progress_and_turn(monkeypatch):
    session = fighter()
    before = session.to_dict()
    checkpoint = session.dice.checkpoint()

    def fail(*args):
        raise ValueError("simulated event validation failure")

    monkeypatch.setattr(WorldMemory, "append", fail)
    with pytest.raises(ValueError):
        session.submit("помочь разгрузить телегу")
    assert session.to_dict() == before
    assert session.dice.checkpoint() == checkpoint


def test_out_of_band_state_change_is_rejected_without_new_dice_or_event():
    session = Session(seed=42)
    session.world = replace(session.world, gold=999)
    checkpoint = session.dice.checkpoint()
    with pytest.raises(ValueError, match="outside recorded"):
        session.submit("бросить кубик")
    assert not session.turns
    assert not session.memory.events
    assert session.dice.checkpoint() == checkpoint


@pytest.mark.parametrize(
    "mutation", ["before", "after", "field", "hash", "order", "missing", "bool", "roll"]
)
def test_invalid_memory_rejected(mutation):
    session = Session(seed=42)
    session.submit("взять поручение")
    session.submit("бросить кубик")
    data = copy.deepcopy(session.to_dict())
    event = data["memory"]["events"][0]
    change = next(c for c in event["changes"] if c["field"] == "world.basket")
    if mutation == "before":
        change["before"] = 7
    elif mutation == "after":
        change["after"] = 500
    elif mutation == "field":
        change["field"] = "world.arbitrary"
    elif mutation == "hash":
        event["after_hash"] = "0" * 64
    elif mutation == "order":
        event["turn_index"] = 2
    elif mutation == "missing":
        data["memory"]["events"].pop()
    elif mutation == "bool":
        change["after"] = True
    else:
        data["memory"]["events"][1]["roll_indices"] = [2]
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_old_v6_starts_memory_at_final_state_without_replaying_and_saves_v7(tmp_path):
    raw = (Path(__file__).parent / "fixtures" / "save-v6.json").read_bytes()
    slots = SaveSlots(tmp_path / "saves")
    slots.directory.mkdir()
    (slots.directory / "slot-1.json").write_bytes(raw)
    session = slots.load(1)
    assert not session.memory.events
    assert session.memory.base_turn == 3
    assert session.combat.surprise
    assert (slots.directory / "slot-1.json").read_bytes() == raw
    session.submit("атаковать волка")
    assert session.memory.events[0].turn_index == 4
    assert session.memory.events[0].roll_indices == (2, 3)
    slots.save(2, session)
    assert json.loads((slots.directory / "slot-2.json").read_bytes())["schema_version"] == 18
    assert slots.load(2).to_dict() == session.to_dict()
    assert slots.load(2).submit("бросить кубик").roll.value == 17
    assert (slots.directory / "slot-1.json").read_bytes() == raw


def test_legacy_editor_is_an_event_and_roundtrips():
    session = Session(seed=42)
    session.edit_character(Character(name="Мира", strength=18))
    changes = {c.field: c.after for c in session.memory.events[0].changes}
    assert changes["hero.name"] == "Мира"
    assert changes["hero.strength"] == 18
    assert Session.from_dict(session.to_dict()).character.name == "Мира"


def test_recent_dialogue_is_bounded_authoritative_and_keeps_saved_prose_two():
    from rpg_vkr.narrative.context import recent_dialogue
    from rpg_vkr.narrative.records import Narration

    session = Session(seed=42)
    for _ in range(5):
        session.submit("поговорить с жительницей")
    frame = build_frame(session)
    session.add_narration(
        Narration(5, "local-test:1", "Придуманный дракон.", frame.fingerprint, "narrator-prose-2")
    )
    restored = Session.from_dict(session.to_dict())
    before = restored.to_dict()
    history = recent_dialogue(restored)
    assert len(history) == 3
    assert all(
        len(row["player_message"]) <= 200 and len(row["confirmed_result"]) <= 350 for row in history
    )
    assert "дракон" not in str(history)
    assert "5 золотых" in str(history)
    assert restored.to_dict() == before
    assert restored.narrations[-1].prompt_version == "narrator-prose-2"


def test_context_contains_only_local_actors_and_public_facts_and_never_hidden_wallet():
    session = Session(seed=42, world=WorldState(shop_gold=731, shop_stock=29))
    frame = build_frame(session)
    text = json.dumps(frame.to_dict(), ensure_ascii=False)
    assert "Серый волк" not in text
    assert "Кабан" not in text
    assert "731" not in text and "shop_gold" not in text
    assert "29" not in text and "shop_stock" not in text
    assert "merchant" not in text
    session.submit("узнать дорогу на рынок")
    session.submit("идти на рынок")
    session.submit("подойти к торговцу")
    session.submit("продать бинт")
    frame = build_frame(session)
    assert "731" not in json.dumps(frame.to_dict(), ensure_ascii=False)
    assert "732" not in json.dumps(frame.to_dict(), ensure_ascii=False)
    assert "29" not in " ".join(frame.memories)  # Internal stock deltas stay private.
    before = session.to_dict()
    fingerprint = frame.fingerprint
    for _ in range(5):
        assert build_frame(session).fingerprint == fingerprint
    assert session.to_dict() == before


def test_model_prose_is_separate_from_state_rng_memory_and_restores_as_plain_text():
    session = fighter()
    frame = build_frame(session)
    note = Narration(0, "local-test:1", "<b>У ворот тихо.</b>", frame.fingerprint)
    before_world, before_memory = session.world, session.memory
    rng = session.dice.checkpoint()
    session.add_narration(note)
    assert session.world == before_world and session.memory == before_memory
    assert session.dice.checkpoint() == rng
    assert Session.from_dict(session.to_dict()).narrations == (note,)
    with pytest.raises(ValueError):
        session.add_narration(note)
    session.submit("осмотреться")
    with pytest.raises(ValueError):
        session.add_narration(note)


def test_wrong_context_hash_and_excessive_prose_are_rejected_without_mutation():
    session = Session(seed=42)
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.add_narration(Narration(0, "local-test:1", "Текст", "0" * 64))
    with pytest.raises(ValueError):
        Narration(0, "local-test:1", "X" * 1501, "0" * 64)
    assert session.to_dict() == before
    assert digest(snapshot(session.world, session.character, session.combat, session.progress))
