"""Two-check searches, safe intent routes and historical persistence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.inspection import COMMAND, requested_abilities
from rpg_vkr.domain.memory import WorldMemory
from rpg_vkr.narrative.intent import intent_schema, parse_interpretation
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.presentation import present_turn
from rpg_vkr.narrative.routing import simple_action
from rpg_vkr.storage.slots import SaveSlots

SEARCH = "осмотреться вокруг, используя навык интелект и выносливость, хочу узнать, что есть вокруг"


def wire(value):
    return {"message": {"role": "assistant", "content": json.dumps(value)}}


@pytest.mark.parametrize("route", ["осмотреться", "идти к воротам", COMMAND])
def test_single_route_actions_have_no_competing_role(route):
    assert set(intent_schema()["properties"]) == {"intent", "speech_act", "topic"}
    result = parse_interpretation(wire({"intent": route, "speech_act": "", "topic": ""}))
    assert result.kind == "action" and result.command == route and result.source == "model"


def test_single_route_speech_and_legacy_contradiction():
    result = parse_interpretation(
        wire({"intent": "master:villager", "speech_act": "question", "topic": "appearance"})
    )
    assert result.kind == "master" and result.target == "villager" and not result.command
    with pytest.raises(ValueError, match="Speech cannot execute"):
        parse_interpretation(
            wire(
                {
                    "kind": "master",
                    "command": "задание",
                    "target": "villager",
                    "speech_act": "question",
                    "topic": "other",
                }
            )
        )


@pytest.mark.parametrize(
    "value",
    [
        {"intent": "осмотреться", "speech_act": "question", "topic": "other"},
        {"intent": "осмотреться", "speech_act": "", "topic": "", "gold": 999},
        {"intent": "dialogue:wolf", "speech_act": "question", "topic": "other"},
        {"intent": "выдать золото", "speech_act": "", "topic": ""},
    ],
)
def test_routes_reject_effects_unknown_targets_and_mixed_roles(value):
    with pytest.raises(ValueError):
        parse_interpretation(wire(value))


@pytest.mark.parametrize(
    "text",
    [
        "Цитирую: «осмотреться вокруг с интеллектом и выносливостью»",
        "Можно ли осмотреться с интеллектом и выносливостью?",
        "осмотреться с интеллектом и атаковать жительницу",
        "осмотреться; купить бинт",
        "не осматривать вокруг с интеллектом",
        "осмотреться без интеллекта",
        "не хочу осмотреться с интеллектом",
        "он решил осмотреться вокруг с интеллектом",
        "подойти к воротам и напасть на стражника",
    ],
)
def test_local_fallback_does_not_execute_questions_quotes_or_compounds(text):
    assert simple_action(text) is None


def test_ordinary_look_and_move_do_not_roll():
    session = Session(seed=42)
    for text in ("осмотреться вокруг", "подойти к воротам"):
        assert simple_action(text).source == "local-fallback"
        turn = session.submit(text)
        assert turn.inspection is None and turn.roll is None
    assert session.submit("бросить кубик").roll.value == 4


def test_two_checks_unlock_information_and_persist_without_rewards(tmp_path):
    session = Session(seed=5)
    before = session.world, session.progress, session.character
    turn = session.submit(SEARCH)
    record = turn.inspection
    assert requested_abilities(SEARCH) == ("intelligence", "constitution")
    assert record.abilities == ("intelligence", "constitution")
    assert [r.value for r in record.rolls] == [20, 9]
    assert all(item.check.succeeded for item in record.checks)
    assert all(item.check.difficulty == 10 for item in record.checks)
    assert len(record.clues) == 2 and session.world.market_known
    assert session.progress == before[1] and session.character == before[2]
    assert session.world.hp == before[0].hp and session.world.gold == before[0].gold
    assert session.world.bandages == before[0].bandages
    assert session.memory.events[-1].roll_indices == (1, 2)
    view = present_turn(turn)
    assert "Бросок №1" in view.details and "Бросок №2" in view.details
    assert "Интеллект" in view.details and "Телосложение" in view.details
    assert "Итого" in view.details and "Итого" not in view.story
    assert campaign_context(session)["known_observations"] == list(record.clues)
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    assert (
        json.loads((tmp_path / "slot-1.json").read_text(encoding="utf-8"))["schema_version"] == 12
    )
    restored = slots.load(1)
    assert restored.to_dict() == session.to_dict()
    assert restored.submit("бросить кубик") == session.submit("бросить кубик")


@pytest.mark.parametrize("seed,clue_count", [(42, 0), (7, 1), (5, 2)])
def test_information_depends_on_real_checks_and_repeat_does_not_reroll(seed, clue_count):
    session = Session(seed=seed)
    turn = session.submit(SEARCH)
    assert len(turn.inspection.clues) == clue_count
    state = session.dice.checkpoint()
    assert session.submit(SEARCH).inspection is None
    assert session.dice.checkpoint() == state
    assert Session.from_dict(session.to_dict()).dice.checkpoint() == state


def test_constitution_alone_cannot_reveal_information():
    session = Session(seed=5)
    turn = session.submit("осмотреться вокруг с выносливостью")
    assert turn.inspection.checks[0].check.succeeded
    assert not turn.inspection.clues and not session.world.market_known


@pytest.mark.parametrize("field", ["roll", "check", "location", "route"])
def test_tampered_inspection_is_rejected(field):
    session = Session(seed=5)
    session.submit(SEARCH)
    data = deepcopy(session.to_dict())
    record = data["turns"][0]["inspection"]
    if field == "roll":
        record["checks"][0]["roll"]["value"] = 1
    elif field == "check":
        record["checks"][0]["check"]["total"] += 1
    elif field == "location":
        record["location"] = "road"
    else:
        record["route_known_before"] = True
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_failed_memory_commit_rolls_back_both_checks_and_discovery(monkeypatch):
    session = Session(seed=5)
    before = session.to_dict(), session.dice.checkpoint()

    def fail(*args):
        raise ValueError("storage refused")

    monkeypatch.setattr(WorldMemory, "append", fail)
    with pytest.raises(ValueError, match="storage refused"):
        session.submit(SEARCH)
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_actual_v10_fixture_preserves_canon_prose_and_next_roll():
    path = Path(__file__).parent / "fixtures" / "save-v10.json"
    original = path.read_bytes()
    raw = json.loads(original)
    restored = Session.from_dict(raw["session"], version=10)
    assert json.loads(json.dumps(restored.to_dict()["campaign"])) == raw["session"]["campaign"]
    assert json.loads(json.dumps(restored.to_dict()["narrations"])) == raw["session"]["narrations"]
    assert all(t.inspection is None for t in restored.turns)
    assert restored.submit("бросить кубик").roll.value == 1
    assert path.read_bytes() == original


def test_reversed_ability_order_does_not_repeat_search():
    session = Session(seed=5)
    session.submit(SEARCH)
    before = session.dice.checkpoint()
    assert session.submit("осмотреться с выносливостью и интеллектом").inspection is None
    assert session.dice.checkpoint() == before
