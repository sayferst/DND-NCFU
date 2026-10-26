"""Revision four exercises the actual Session, queue, costs, records and cold replay."""

from copy import deepcopy

import pytest
from test_adventure import world_value
from test_gameplay_integration import hero as first_hero

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.storage.slots import SaveSlots


def hero(*, profile="warrior", seed=13, extra=0, long_names=False):
    old = first_hero(profile=profile, skills={"arcana": 1})
    session = Session.create_hero(old.character, "fighter", seed=seed)
    session.enable_gameplay(old.gameplay["identity"], revision=4)
    value = world_value()
    roster = [("first", 12), ("second", 12), ("friend", 20)]
    roster += [(f"extra_{index}", 12) for index in range(extra)]
    for id, hp in roster:
        props = {"hp_max": hp, "strength": 8, "dexterity": 8}
        if id == "friend":
            props.update(party_ally=True, strength=16, armour="mail")
        value["definitions"].append(
            {
                "id": id + "_type",
                "name": id + ("а" * 85 if long_names else ""),
                "kind": "actor",
                "categories": ["npcs"],
                "properties": props,
            }
        )
        value["entities"].append(
            {
                "id": id,
                "definition_id": id + "_type",
                "parent_id": "pier",
                "state": {"hp": hp, "disposition": "friendly" if id == "friend" else "hostile"},
            }
        )
    session.start_world(build_world(value, session, "synthetic-model"))
    return session


def perform(session, command, **args):
    return session.perform_gameplay(command, args, "test_" + str(len(session.turns)))


def roundtrip(session):
    raw = session.to_dict()
    other = Session.from_dict(deepcopy(raw))
    assert other.schema_version == 27
    assert other.to_dict() == raw
    assert other.dice.roll_d20() == session.dice.roll_d20()


def test_group_queue_is_shared_and_allies_really_act_against_enemies():
    session = hero()
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    battle = session.gameplay["battle"]
    assert set(battle["order"]) == {"hero", "first", "second", "friend"}
    assert battle["order"][battle["cursor"]] == "hero"
    for _ in range(12):
        if not session.in_combat or session.world.hp == 0:
            break
        live = [id for id in ["first", "second"] if id not in session.gameplay["victories"]]
        if session.gameplay["st"] < 2:
            perform(session, "recover")
        else:
            perform(session, "attack", target=live[0], lethal=0)
    outcomes = [a for t in session.turns for a in t.gameplay["result"]["attacks"]]
    assert any(
        a["actor_id"] == "friend" and a["target_id"] in {"first", "second"} for a in outcomes
    )
    assert any(a["actor_id"] in {"first", "second"} for a in outcomes)
    assert all(a["resolver_version"] == "combat-d20-1" for a in outcomes)
    assert session.gameplay["npc_resources"]["friend"]["st"] < 20
    assert set(session.gameplay["victories"]) == {"first", "second"}
    assert session.d20_progress.xp == 100
    assert session.gameplay["last_battle"]["status"] == "won"
    roundtrip(session)


def test_no_two_actions_in_one_round_and_idempotent_request():
    session = hero()
    args = {"enemies": ["first", "second"], "allies": ["friend"]}
    turn = session.perform_gameplay("encounter", args, "start")
    saved = session.to_dict()
    assert session.perform_gameplay("encounter", args, "start") == turn
    assert session.to_dict() == saved
    perform(session, "dodge")
    events = [
        e
        for t in session.turns
        for e in t.gameplay["result"]["battle_events"]
        if e["kind"] in {"attack", "recover", "move"}
    ]
    keys = [(e["actor"], e["round"]) for e in events]
    assert len(keys) == len(set(keys))
    roundtrip(session)


@pytest.mark.parametrize(
    "enemies,allies",
    [
        (["first", "first"], []),
        (["first"], ["first"]),
        (["missing"], []),
        (["first"], ["seller"]),
        (["hero"], []),
        (["watcher"], []),
    ],
)
def test_invalid_roster_does_not_change_rng_or_world(enemies, allies):
    session = hero()
    raw, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        perform(session, "encounter", enemies=enemies, allies=allies)
    assert session.to_dict() == raw and session.dice.checkpoint() == rng


def test_selecting_another_opponent_is_legal_and_unrelated_targets_are_rejected():
    session = hero()
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    perform(session, "attack", target="second", lethal=0)
    raw, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        perform(session, "attack", target="seller", lethal=0)
    assert session.to_dict() == raw and session.dice.checkpoint() == rng
    roundtrip(session)


def test_spell_and_mp_are_real_actions_in_group_queue():
    session = hero(profile="mage")
    perform(session, "learn", spell="spark")
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    mp = session.gameplay["mp"]
    perform(session, "cast", spell="spark", target="second")
    assert session.gameplay["mp"] == mp - 3
    assert any(e["kind"] == "spell" for e in session.turns[-1].gameplay["result"]["battle_events"])
    roundtrip(session)


def test_save_sqlite_export_corrupt_queue_and_safe_retreat(tmp_path):
    from rpg_vkr.storage.knowledge import export_session, restore_session

    session = hero()
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    slots = SaveSlots(tmp_path / "slots")
    slots.save(1, session)
    assert slots.load(1).to_dict() == session.to_dict()
    export_session(session, tmp_path / "world.sqlite3")
    assert restore_session(tmp_path / "world.sqlite3").to_dict() == session.to_dict()
    raw = deepcopy(session.to_dict())
    raw["turns"][-1]["gameplay"]["result"]["state"]["battle"]["order"].reverse()
    with pytest.raises(ValueError):
        Session.from_dict(raw)
    before = session.world.hp
    perform(session, "retreat")
    assert not session.in_combat and session.world.hp == before
    assert session.gameplay["last_battle"]["status"] == "retreated"
    roundtrip(session)


def test_actual_revision26_fixture_preserves_canonical_data_and_next_rng():
    import hashlib
    import json
    from dataclasses import asdict
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    meta = json.loads(
        (
            root / "docs/validation/training-and-encounters-2026-10-26/fixture-v26-source.json"
        ).read_text()
    )
    raw = (root / "tests/fixtures/session-v26-factions.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == meta["fixture_sha256"]
    value = json.loads(raw)
    session = Session.from_dict(value["session"], version=26)
    assert session.schema_version == 26
    assert json.loads(json.dumps(session.to_dict())) == value["session"]
    assert asdict(session.dice.roll_d20()) == meta["next_roll"]
    assert meta["source_commit"] == "b88df8b"


def test_group_is_connected_to_real_qt_buttons(qt_app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    from rpg_vkr.ui import narrator_panel
    from rpg_vkr.ui.main_window import MainWindow

    session = hero()
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "slots"))
    monkeypatch.setattr(window, "_confirm", lambda *_: True)
    monkeypatch.setattr(narrator_panel, "after_action", lambda *_: None)
    for index in range(window.group_enemies.count()):
        row = window.group_enemies.item(index)
        row.setSelected(row.data(Qt.ItemDataRole.UserRole) in {"first", "second"})
    window.group_allies.item(0).setSelected(True)
    window.encounter_start.click()
    assert session.in_combat and len(session.gameplay["battle"]["order"]) == 4
    assert "Очередь" in window.battle_info.text()
    assert not window.encounter_start.isEnabled() and window.recover_st.isEnabled()
    assert {window.gameplay_target.itemData(i) for i in range(window.gameplay_target.count())} == {
        "first",
        "second",
    }
    assert len(window.group_enemies.selectedItems()) == 2
    assert not window.group_enemies.isEnabled()
    window.close()


def test_moving_consumes_action_and_npcs_move_without_a_free_attack():
    session = hero()
    perform(session, "encounter", enemies=["first", "second"], allies=[])
    before = session.world.hp
    turn = perform(session, "move", distance=7)
    assert session.world.hp == before
    assert any(e["kind"] == "move" for e in turn.gameplay["result"]["battle_events"])
    assert not turn.gameplay["result"]["attacks"]
    roundtrip(session)


def test_maximum_roster_with_long_valid_names_can_save_and_replay():
    session = hero(extra=4, long_names=True)
    perform(
        session,
        "encounter",
        enemies=["first", "second", "extra_0", "extra_1", "extra_2", "extra_3"],
        allies=["friend"],
    )
    assert len(session.turns[-1].action) <= 500
    assert len(session.gameplay["battle"]["order"]) == 8
    roundtrip(session)
