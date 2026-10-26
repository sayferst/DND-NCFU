"""Second playable revision: physical stock, conversion, provenance, copper and replay."""

from copy import deepcopy

import pytest
from test_adventure import world_value
from test_gameplay_integration import hero as first_hero

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.storage.catalog import CatalogIndex, live_records
from rpg_vkr.storage.slots import SaveSlots


def hero():
    old = first_hero(seed=13, profile="warrior")
    session = Session.create_hero(old.character, "fighter", seed=13)
    session.enable_gameplay(old.gameplay["identity"], revision=2)
    value = world_value()
    value["definitions"].append(
        {
            "id": "dagger_type",
            "name": "Медный кинжал",
            "kind": "item",
            "categories": ["weapons"],
            "properties": {"damage_dice": "1d4", "hands": 1, "durability": 100},
            "price_cp": 30,
        }
    )
    value["entities"].append(
        {
            "id": "daggers",
            "definition_id": "dagger_type",
            "parent_id": "seller",
            "owner_id": "seller",
            "quantity": 2,
            "state": {"condition": 80},
        }
    )
    value["entities"].append(
        {"id": "iron", "definition_id": "mat_iron", "parent_id": "pier", "quantity": 3}
    )
    session.start_world(build_world(value, session, "synthetic-model"))
    return session


def perform(session, command, **args):
    return session.perform_gameplay(command, args, "test_" + str(len(session.turns)))


def roundtrip(session):
    raw = session.to_dict()
    restored = Session.from_dict(deepcopy(raw))
    assert restored.schema_version == 25
    assert restored.to_dict() == raw
    assert restored.dice.roll_d20() == session.dice.roll_d20()


def test_buy_split_stacks_sell_and_preserve_exact_pennies_and_wallet():
    session = hero()
    before, rng = session.to_dict(), session.dice.checkpoint()
    preview = session.preview_gameplay(
        "trade_world", {"merchant": "seller", "item": "daggers", "operation": "buy", "quantity": 1}
    )
    assert preview["transaction"]["price_cp"] == 24
    assert session.to_dict() == before and session.dice.checkpoint() == rng
    turn = session.submit_trade("Покупаю медный кинжал", "seller", "daggers", "buy", 1)
    split = turn.gameplay["result"]["transaction"]["moved_id"]
    assert split != "daggers"
    assert session.world.gold * 100 + session.gameplay["copper"] == 776
    assert next(e for e in session.catalog.entities if e.id == "seller").state["gold_cp"] == 1024
    index = CatalogIndex(session)
    try:
        assert index.lookup(split, public=False)["definition"]["id"] == "dagger_type"
    finally:
        index.close()
    session.submit_trade("Продаю купленный кинжал", "seller", split, "sell", 1)
    assert session.world.gold * 100 + session.gameplay["copper"] == 788
    assert next(e for e in session.catalog.entities if e.id == "seller").state["gold_cp"] == 1012
    roundtrip(session)


def test_equipment_conversion_preserves_name_price_source_and_actual_weapon_die():
    session = hero()
    turn = session.submit_trade("Куплю кинжал", "seller", "daggers", "buy", 1)
    split = turn.gameplay["result"]["transaction"]["moved_id"]
    turn = perform(session, "adopt", item=split)
    value = turn.gameplay["result"]["state"]["items"][-1]
    assert value["name"] == "Медный кинжал"
    assert value["price_cp"] == 30 and value["durability"] == 16
    assert value["source"]["thing"]["id"] == split
    assert not any(t.id == split for t in session.interaction_state().things)
    _, records = live_records(session)
    assert split not in records
    assert records[value["id"]]["owner_id"] == "hero"
    perform(session, "equip", item=value["id"])
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    for _attempts in range(1, 11):
        session.submit_actor_attempt(
            "атакую Морока", "watcher", "attack", False, "атака", "synthetic-model"
        )
        attack = next(
            a for a in session.turns[-1].gameplay["result"]["attacks"] if a["actor_id"] == "hero"
        )
        if attack["hit"]:
            break
    assert attack["hit"] and attack["damage_roll"]["expression"] in {"1d4", "2d4"}
    assert session.gameplay["items"][-1]["durability"] == 16 - _attempts
    roundtrip(session)


def test_cannot_turn_cheap_world_weapon_into_full_price_starter_catalog():
    session = hero()
    turn = session.submit_trade("Куплю кинжал", "seller", "daggers", "buy", 1)
    split = turn.gameplay["result"]["transaction"]["moved_id"]
    perform(session, "adopt", item=split)
    id = session.gameplay["items"][-1]["id"]
    turn = session.submit_trade("Продаю свой кинжал", "seller", id, "sell", 1)
    assert turn.gameplay["result"]["transaction"]["price_cp"] == 12
    assert session.world.gold * 100 + session.gameplay["copper"] == 788
    turn = session.submit_trade("Куплю свой кинжал обратно", "seller", id, "buy", 1)
    assert turn.gameplay["result"]["transaction"]["price_cp"] == 24
    assert session.world.gold * 100 + session.gameplay["copper"] == 764
    roundtrip(session)


def test_unregistered_shop_stock_is_not_created_in_generated_world():
    session = hero()
    before = session.to_dict()
    with pytest.raises(ValueError):
        perform(session, "buy", merchant="seller", item="shop_seller_sword")
    assert session.to_dict() == before


def test_split_materials_can_be_prepared_without_losing_the_remaining_type():
    session = hero()
    session.submit_interaction("беру часть железа", WorldPlan((Step("take", "iron", 1),)))
    # Find the actual split without depending on inventory ordering.
    split = next(t.id for t in session.interaction_state().carried() if t.name == "Железо")
    perform(session, "prepare", item=split)
    session.submit_interaction("беру остальное железо", WorldPlan((Step("take", "iron", 2),)))
    perform(session, "prepare", item="iron")
    perform(session, "prepare", item="iron")
    assert not any(t.id == "iron" for t in session.interaction_state().things)
    assert len([i for i in session.gameplay["items"] if i["kind"] == "iron"]) == 5
    roundtrip(session)


@pytest.mark.parametrize(
    "command,args",
    [
        ("adopt", {"item": "daggers"}),
        ("adopt", {"item": "rope"}),
        (
            "trade_world",
            {"merchant": "seller", "item": "daggers", "operation": "buy", "quantity": 3},
        ),
        (
            "trade_world",
            {"merchant": "seller", "item": "legacy_gold", "operation": "sell", "quantity": 1},
        ),
    ],
)
def test_invalid_physical_operations_do_not_mutate_resources_or_rng(command, args):
    session = hero()
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.perform_gameplay(command, args, "invalid")
    assert session.to_dict() == before and session.dice.checkpoint() == rng


def test_copper_ui_uses_finite_stock_and_calls_real_session(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from rpg_vkr.ui.context_actions import show_trade
    from rpg_vkr.ui.copper_shop import CopperTradeDialog

    window._session = hero()
    window._refresh_character()
    show_trade(window, "seller")
    dialog = window._trade_dialog
    assert isinstance(dialog, CopperTradeDialog)
    row = next(i for i, value in enumerate(dialog.rows) if value[0] == "daggers")
    dialog.table.selectRow(row)
    dialog.update_quote()
    assert "24 медных" in dialog.execute.text()
    before = len(window._session.turns)
    dialog.execute.click()
    assert len(window._session.turns) == before + 1
    assert window._session.world.gold * 100 + window._session.gameplay["copper"] == 776
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()


def test_physical_rules_use_both_save_paths_and_reject_alias_forgery(tmp_path):
    from rpg_vkr.storage.knowledge import export_session, restore_session

    session = hero()
    session.submit_trade("Куплю один кинжал", "seller", "daggers", "buy", 1)
    session.submit_trade("Куплю второй кинжал", "seller", "daggers", "buy", 1)
    slots = SaveSlots(tmp_path / "slots")
    slots.save(1, session)
    assert slots.load(1).to_dict() == session.to_dict()
    export_session(session, tmp_path / "world.sqlite3")
    assert restore_session(tmp_path / "world.sqlite3").to_dict() == session.to_dict()
    value = deepcopy(session.to_dict())
    value["turns"][-1]["gameplay"]["context"]["aliases"]["invented"] = "daggers"
    with pytest.raises(ValueError):
        Session.from_dict(value)


def test_actual_schema24_fixture_from_committed_runtime_is_unchanged_and_continues_rng():
    import hashlib
    import json
    from dataclasses import asdict
    from pathlib import Path

    from rpg_vkr.domain.combat_record import canonical

    path = Path(__file__).parent / "fixtures/session-v24-playable.json"
    root = Path(__file__).resolve().parents[1]
    metadata = json.loads(
        (
            root / "docs/validation/gameplay-v3-physical-2026-10-26/fixture-v24-source.json"
        ).read_text(encoding="utf-8")
    )
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == metadata["fixture_sha256"]
    value = json.loads(raw)
    session = Session.from_dict(value["session"], version=24)
    assert session.schema_version == 24
    assert canonical(session.to_dict()) == canonical(value["session"])
    assert asdict(session.dice.roll_d20()) == metadata["next_roll"]
    assert metadata["source_commit"] == "899782f"


def test_zero_price_batch_and_exhausted_wallet_are_validated_atomically():
    from dataclasses import replace

    from rpg_vkr.domain.catalog import Catalog, Definition, Entity
    from rpg_vkr.domain.copper_trade import transact_copper
    from rpg_vkr.domain.interactions import Thing

    session = hero()
    catalog = session.catalog
    definition = Definition("tiny_goods", "Мелочь", "item", ("miscellaneous",), {}, price_cp=1)
    entity = Entity("tiny_stack", definition.id, "hero", "hero", 2)
    catalog = Catalog((*catalog.definitions, definition), (*catalog.entities, entity))
    scene = replace(
        session.interaction_state(),
        things=(
            *session.interaction_state().things,
            Thing(entity.id, definition.name, "hero", "hero", 2),
        ),
    )
    before = catalog.to_dict(), scene.to_dict()
    with pytest.raises(ValueError, match="партию"):
        transact_copper(catalog, scene, session.world, 0, "seller", entity.id, "sell", 1, 1, {})
    _, after_scene, world, remainder, receipt = transact_copper(
        catalog, scene, session.world, 0, "seller", entity.id, "sell", 2, 1, {}
    )
    assert receipt["price_cp"] == 1
    assert world.gold == session.world.gold and remainder == 1
    assert catalog.to_dict() == before[0] and scene.to_dict() == before[1]
    assert (
        after_scene.root_holder(next(t for t in after_scene.things if t.id == entity.id))
        == "seller"
    )


def test_ui_adoption_can_be_cancelled_without_consumption(window, monkeypatch):
    from rpg_vkr.ui.gameplay_panel import run

    session = hero()
    turn = session.submit_trade("Покупаю кинжал", "seller", "daggers", "buy", 1)
    id = turn.gameplay["result"]["transaction"]["moved_id"]
    window._session = session
    window._refresh_character()
    before = session.to_dict()
    monkeypatch.setattr(window, "_confirm", lambda *args: False)
    run(window, "adopt", {"item": id})
    assert session.to_dict() == before
    monkeypatch.setattr(window, "_confirm", lambda *args: True)
    run(window, "adopt", {"item": id})
    assert not any(t.id == id for t in session.interaction_state().things)
    assert session.gameplay["items"][-1]["name"] == "Медный кинжал"
    roundtrip(session)


@pytest.mark.parametrize(
    "level,hp,st", [(1, 20, 30), (5, 52, 42), (10, 92, 57), (15, 132, 72), (20, 172, 87)]
)
def test_proposed_resource_formulas_are_bounded_and_versioned(level, hp, st):
    from rpg_vkr.domain.hero_resources import limits

    session = hero()
    assert limits(session.gameplay, session.character, level) == {"hp": hp, "st": st, "mp": 0}
    assert session.world.max_hp == 20
    assert session.gameplay["resource_version"] == "hero-resources-1"


def test_ordinary_movement_consumes_stamina_and_rest_restores_it():
    session = hero()
    before = session.gameplay["st"]
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    assert session.gameplay["st"] == before - 1
    perform(session, "rest")
    assert session.gameplay["st"] == session.gameplay["st_cap"]
    assert session.world.hp == session.world.max_hp
    roundtrip(session)


def test_level_from_real_checks_applies_hp_growth_in_same_atomic_turn():
    old = first_hero(seed=13, profile="warrior")
    session = Session.create_hero(old.character, "fighter", seed=13)
    identity = old.gameplay["identity"] | {
        "skills": {"athletics": 2, "acrobatics": 2, "knowledge": 2, "persuasion": 2}
    }
    session.enable_gameplay(identity, revision=2)
    # A real tutorial victory gives50; five distinct successful categories give50.
    session.submit("идти на дорогу")
    for _ in range(20):
        if not session.combat.actor("wolf").hp:
            break
        session.submit("атаковать волка")
    assert session.d20_progress.xp == 50
    for action in (
        "пытаюсь поднять камень",
        "пытаюсь взобраться на стену",
        "пытаюсь перепрыгнуть ручей",
        "пытаюсь расшифровать надпись",
        "пытаюсь вспомнить сведения",
    ):
        for _ in range(30):
            turn = session.submit_challenge(action)
            if turn.check.succeeded:
                break
        assert turn.check.succeeded
    assert session.d20_progress.level == 2
    assert session.world.max_hp == 28
    assert session.progress.events == ()
    assert session.gameplay["st_cap"] == 33
    roundtrip(session)


def test_stamina_exhaustion_blocks_attack_without_rng_and_retreat_is_still_possible():
    session = hero()
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    session.submit_actor_attempt(
        "атакую Морока", "watcher", "attack", False, "атака", "synthetic-model"
    )
    assert session.in_combat
    while session.gameplay["st"]:
        perform(session, "move", distance=7)
    assert session.gameplay["st"] == 0
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="ST"):
        session.submit_actor_attempt(
            "атакую Морока", "watcher", "attack", False, "атака", "synthetic-model"
        )
    assert session.to_dict() == before and session.dice.checkpoint() == rng
    perform(session, "retreat")
    assert not session.in_combat
    perform(session, "rest")
    assert session.gameplay["st"] == 30
    roundtrip(session)


@pytest.mark.parametrize(
    "talent,hp,st,mp", [("resilient", 22, 30, 8), ("enduring", 20, 34, 8), ("focus", 20, 30, 12)]
)
def test_additional_talents_change_real_starting_resources_and_survive_load(talent, hp, st, mp):
    old = first_hero(seed=13, profile="mage")
    session = Session.create_hero(old.character, "fighter", seed=13)
    session.enable_gameplay(old.gameplay["identity"] | {"talent": talent}, revision=2)
    assert (session.world.max_hp, session.gameplay["st_cap"], session.gameplay["mp_cap"]) == (
        hp,
        st,
        mp,
    )
    assert session.gameplay["mp"] == mp
    roundtrip(session)


def test_additional_talent_is_a_real_spend_and_is_not_free_repeated_healing():
    session = hero()
    perform(session, "talent", talent="resilient")
    assert session.world.hp == session.world.max_hp == 22
    before = session.to_dict()
    with pytest.raises(ValueError):
        perform(session, "talent", talent="resilient")
    with pytest.raises(ValueError):
        perform(session, "talent", talent="enduring")
    assert session.to_dict() == before
    roundtrip(session)


def test_creation_preview_matches_actual_resource_limits(qt_app):
    from rpg_vkr.ui.creation_dialog import CreationDialog

    dialog = CreationDialog()
    dialog.use_gameplay.setChecked(True)
    dialog.profile_choice.setCurrentIndex(dialog.profile_choice.findData("mage"))
    dialog.initial_talent.setCurrentIndex(dialog.initial_talent.findData("focus"))
    session = dialog.create_session()
    assert f"HP {session.world.max_hp}" in dialog.creation_summary.text()
    assert f"ST {session.gameplay['st_cap']}" in dialog.creation_summary.text()
    assert f"MP {session.gameplay['mp_cap']}" in dialog.creation_summary.text()
    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize(
    "properties",
    [
        {"weapon": "sword", "hands": 2},
        {"weapon": "sword", "damage_dice": "2d8"},
        {"equipment_slot": "shield", "shield_bonus": 8},
        {"weapon": "dagger", "attack_bonus": 5},
    ],
)
def test_inconsistent_equipment_cards_are_rejected_instead_of_getting_free_bonuses(properties):
    from rpg_vkr.domain.catalog import Definition
    from rpg_vkr.domain.gameplay_v2 import equipment_kind

    definition = Definition("bad_card", "Противоречивый предмет", "item", ("weapons",), properties)
    with pytest.raises(ValueError):
        equipment_kind(definition)


def test_model_context_excludes_closed_shop_and_includes_supported_equipment_contract(window):
    from rpg_vkr.narrative.master import campaign_context
    from rpg_vkr.ui.narrator_panel import catalog_context

    session = hero()
    perform(session, "wait", minutes=14 * 60)
    window._session = session
    state = catalog_context(window, "что рядом")
    assert "seller" not in state["actors_here"]
    assert state["equipment_rules"]["weapons"]["sword"] == {"damage_dice": "1d8", "hands": 1}
    campaign = campaign_context(session)
    assert not next(a for a in campaign["validation_roster"] if a["id"] == "seller")["here"]


def test_world_clock_closes_old_trade_contact_before_direct_command_can_bypass_schedule():
    old = first_hero(seed=13, profile="warrior")
    session = Session.create_hero(old.character, "fighter", seed=13)
    session.enable_gameplay(old.gameplay["identity"], revision=2)
    session.submit("узнать дорогу на рынок")
    session.submit("идти на рынок")
    session.submit("подойти к торговцу")
    assert session.world.trading
    perform(session, "wait", minutes=12 * 60)
    assert not session.world.trading and not session.actor_is_here("merchant")
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.submit("купить бинт")
    assert session.to_dict() == before
    roundtrip(session)


def test_passive_tick_context_cannot_fake_primary_hp_before_resource_recalculation():
    session = hero()
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    value = deepcopy(session.to_dict())
    value["turns"][-1]["gameplay"]["context"]["world"]["max_hp"] = 1000
    with pytest.raises(ValueError):
        Session.from_dict(value)


def test_defeated_new_hero_cannot_be_revived_by_rest():
    from rpg_vkr.domain.catalog import Definition, Entity

    session = hero()
    definition = Definition(
        "giant_type",
        "Исполин",
        "actor",
        ("creatures",),
        {"hp_max": 1000, "strength": 30, "dexterity": 30, "weapon": "axe"},
    )
    session.register_catalog(
        "замечаю исполина",
        (definition,),
        (Entity("giant", definition.id, "pier"),),
        "синтетический противник",
        "synthetic-model",
    )
    for _ in range(10):
        if session.world.hp == 0:
            break
        perform(session, "attack", target="giant", lethal=0)
    assert session.world.hp == 0
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        perform(session, "rest")
    assert session.to_dict() == before and session.dice.checkpoint() == rng
    roundtrip(session)
