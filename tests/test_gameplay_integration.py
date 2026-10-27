"""Playable v3: actual Session/UI commands, conserved resources and both storage paths."""

from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.gameplay import PROFILES, SPECIES, hero_combatant
from rpg_vkr.domain.gameplay_commands import parse
from rpg_vkr.domain.progression import ARCHETYPES
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.knowledge import export_session, restore_session
from rpg_vkr.storage.slots import SaveSlots


def hero(seed=13, profile="mage", skills=None, talent=""):
    character = Character(**dict(zip(ABILITY_NAMES, ARCHETYPES["fighter"].scores, strict=True)))
    session = Session.create_hero(character, "fighter", seed=seed)
    session.enable_gameplay(
        {
            "species": "human",
            "profile": profile,
            "age": 20,
            "background": "Путник",
            "appearance": "Дорожная одежда",
            "skills": skills or {},
            "talent": talent,
        }
    )
    return session


def perform(session, command, **args):
    return session.perform_gameplay(command, args, "test_" + str(len(session.turns)))


def roundtrip(session):
    raw = session.to_dict()
    restored = Session.from_dict(deepcopy(raw))
    assert restored.to_dict() == raw
    assert restored.dice.roll_d20() == session.dice.roll_d20()


@pytest.mark.parametrize("profile", PROFILES)
def test_new_profiles_create_real_items_and_replay(profile):
    session = hero(profile=profile)
    assert session.schema_version == 24
    assert session.d20_progress.skill_points == 13
    assert len({i["id"] for i in session.gameplay["items"]}) == len(session.gameplay["items"])
    assert len(session.extra_inventory_rows) == len(session.gameplay["items"])
    roundtrip(session)


@pytest.mark.parametrize("species", SPECIES)
def test_species_is_saved_identity_not_unapproved_free_stats(species):
    session = hero()
    identity = dict(session._gameplay["identity"], species=species)
    other = Session.create_hero(session.character, "fighter", seed=13)
    other.enable_gameplay(identity)
    assert other.character == session.character
    assert Session.from_dict(other.to_dict()).gameplay["identity"]["species"] == species


def test_owned_equipment_changes_real_attack_die_and_ac():
    sword = hero(profile="warrior", seed=1)
    dagger = hero(profile="mage", seed=1)
    for session in (sword, dagger):
        session.submit("идти на дорогу")
    a = sword.submit("атаковать волка").gameplay["result"]["attacks"]
    b = dagger.submit("атаковать волка").gameplay["result"]["attacks"]
    assert next(x for x in a if x["actor_id"] == "hero")["damage_roll"]["expression"] == "1d8"
    assert next(x for x in b if x["actor_id"] == "hero")["damage_roll"]["expression"] == "1d4"
    shield = hero()
    before = hero_combatant(shield.gameplay, shield.world, shield.character, shield.d20_progress)
    perform(shield, "equip", item="kit_2")
    after = hero_combatant(shield.gameplay, shield.world, shield.character, shield.d20_progress)
    assert not before.shield and after.shield
    perform(shield, "unequip", slot="shield")
    roundtrip(shield)


@pytest.mark.parametrize(
    "command,args",
    [
        ("equip", {"item": "imaginary_sword"}),
        ("cast", {"spell": "flame", "target": "guard"}),
        ("learn", {"spell": "flame"}),
        ("craft", {"recipe": "dagger"}),
        ("wait", {"minutes": -1}),
        ("move", {"distance": 99}),
        ("attack", {"target": "wolf", "lethal": 0}),
        ("attribute", {"ability": "strength"}),
        ("buy", {"merchant": "guard", "item": "kit_0"}),
    ],
)
def test_rejected_action_is_atomic_including_rng(command, args):
    session = hero()
    raw, checkpoint = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.perform_gameplay(command, args, "bad")
    assert session.to_dict() == raw
    assert session.dice.checkpoint() == checkpoint


def test_victory_uses_one_xp_source_and_roundtrips():
    session = hero(seed=1, profile="warrior")
    session.submit("идти на дорогу")
    for _ in range(20):
        if not session.combat.actor("wolf").hp or not session.world.hp:
            break
        session.submit("атаковать волка")
    assert session.combat.actor("wolf").hp == 0
    assert session.d20_progress.xp == 50
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.submit("атаковать волка")
    assert session.to_dict() == before
    assert "нелетальный" in session.turns[-1].text
    roundtrip(session)


def test_active_new_battle_blocks_learning_trade_world_mutations():
    session = hero()
    session.submit("идти на дорогу")
    session.submit("атаковать волка")
    assert session.in_combat
    for call in (
        lambda: session.train_skill("repair"),
        lambda: session.submit("идти к воротам"),
        lambda: perform(session, "rest"),
        lambda: perform(session, "equip", item="kit_2"),
        lambda: session.submit_challenge("пытаюсь взобраться на стену"),
    ):
        before = session.to_dict()
        with pytest.raises(ValueError):
            call()
        assert session.to_dict() == before
    perform(session, "retreat")
    assert not session.in_combat
    roundtrip(session)


def test_magic_learning_mp_components_concentration_expiry_and_restart():
    session = hero(skills={"arcana": 1})
    perform(session, "learn", spell="light")
    perform(session, "learn", spell="ward")
    perform(session, "cast", spell="light", target="hero")
    assert session.gameplay["mp"] == 7
    assert session.gameplay["effects"][0]["kind"] == "light"
    perform(session, "cast", spell="ward", target="hero")
    assert session.gameplay["mp"] == 4
    before = session.to_dict()
    with pytest.raises(ValueError):
        perform(session, "cast", spell="ward", target="hero")
    assert session.to_dict() == before
    perform(session, "wait", minutes=60)
    assert session.gameplay["effects"] == []
    perform(session, "rest")
    assert session.gameplay["mp"] == session.gameplay["mp_cap"]
    assert "MP" in build_frame(session).scene
    roundtrip(session)


def test_magical_attack_uses_real_npc_and_retaliation():
    session = hero(seed=1, skills={"arcana": 1})
    perform(session, "learn", spell="spark")
    session.submit("идти на дорогу")
    turn = perform(session, "cast", spell="spark", target="wolf")
    assert session.gameplay["mp"] == 5
    assert turn.gameplay["result"]["rolls"]
    assert "Спасбросок" in turn.text
    assert session.in_combat or session.combat.actor("wolf").hp == 0
    if session.in_combat:
        session.submit("атаковать волка")
    roundtrip(session)


def test_craft_consumes_materials_once_on_success_or_failure():
    session = hero(skills={"smithing": 2, "repair": 1})
    turn = perform(session, "craft", recipe="dagger")
    assert not [i for i in session.gameplay["items"] if i["kind"] == "iron"]
    assert session.gameplay["minute"] == 510
    before = session.to_dict()
    assert (
        session.perform_gameplay("craft", {"recipe": "dagger"}, turn.gameplay["request_id"]) is turn
    )
    assert session.to_dict() == before
    with pytest.raises(ValueError):
        perform(session, "craft", recipe="dagger")
    with pytest.raises(ValueError):
        session.perform_gameplay("rest", {}, turn.gameplay["request_id"])
    roundtrip(session)


def test_money_is_exact_and_stock_transfer_cannot_create_arbitrage():
    session = hero()
    session.submit("узнать дорогу на рынок")
    session.submit("идти на рынок")
    initial = session.world.gold * 100 + session.gameplay["copper"]
    turn = perform(session, "buy", merchant="merchant", item="shop_merchant_cloth")
    assert initial - (session.world.gold * 100 + session.gameplay["copper"]) == 30
    assert session.world.shop_gold * 100 + session.gameplay["shop_copper"] == 2030
    perform(session, "sell", merchant="merchant", item="shop_merchant_cloth")
    assert session.world.gold * 100 + session.gameplay["copper"] == initial - 15
    assert (
        session.perform_gameplay(
            "buy",
            {"merchant": "merchant", "item": "shop_merchant_cloth"},
            turn.gameplay["request_id"],
        )
        is turn
    )
    roundtrip(session)


def test_talents_apply_to_real_checks_and_reject_duplicate_spending():
    session = hero(skills={"arcana": 1})
    perform(session, "talent", talent="scholar")
    assert session.effective_character.intelligence == 9
    before = session.to_dict()
    with pytest.raises(ValueError):
        perform(session, "talent", talent="medic")
    assert session.to_dict() == before
    session.submit_challenge(
        "пытаюсь вспомнить сведения о древнем храме",
        assessment={
            "ability": "intelligence",
            "dc": 10,
            "purpose": "вспомнить сведения",
            "skill": "knowledge",
        },
    )
    roundtrip(session)


def test_schedule_closes_contact_and_persists_npc_rumour_sources():
    session = hero()
    perform(session, "wait", minutes=14 * 60)
    assert not session.actor_is_here("guard")
    with pytest.raises(ValueError):
        perform(session, "attack", target="guard", lethal=0)
    perform(session, "wait", minutes=10 * 60)
    assert session.actor_is_here("guard")
    assert session.gameplay["npc"]["guard"]["activity"] == "working"
    assert session.gameplay["faction_projects"]["artisans"] == 1
    roundtrip(session)


@pytest.mark.parametrize(
    "value",
    ["не выучить искру", "если могу применить свет", "говорю применить свет", "хочу отдохнуть"],
)
def test_negation_condition_and_speech_do_not_execute(value):
    assert parse(value) is None


def test_text_commands_use_session_and_survive_all_storage_paths(tmp_path):
    session = hero(skills={"arcana": 1})
    session.submit("выучить свет")
    session.submit("применить свет")
    assert session.gameplay["mp"] == 7
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    assert slots.load(1).to_dict() == session.to_dict()
    export_session(session, tmp_path / "campaign.sqlite3")
    assert restore_session(tmp_path / "campaign.sqlite3").to_dict() == session.to_dict()
    repo = CampaignRepository(tmp_path / "archive.sqlite3")
    repo.sync(session)
    assert repo.load(repo.identity(session)).to_dict() == session.to_dict()


@pytest.mark.parametrize("path", ["mp", "world", "roll", "context", "ownership"])
def test_corrupted_history_cannot_silently_grant_effects(path):
    session = hero(skills={"arcana": 1})
    perform(session, "learn", spell="light")
    perform(session, "cast", spell="light", target="hero")
    raw = deepcopy(session.to_dict())
    record = raw["turns"][-1]["gameplay"]
    if path == "mp":
        raw["gameplay"]["state"]["mp"] += 1
    elif path == "world":
        record["result"]["world"]["gold"] += 100
    elif path == "roll":
        record["result"]["rolls"] = [{"index": 1, "value": 20}]
    elif path == "context":
        record["context"]["world"]["gold"] += 100
    else:
        record["result"]["state"]["items"][0]["owner"] = "merchant"
    with pytest.raises(ValueError):
        Session.from_dict(raw)


def generated():
    from test_adventure import world_value

    from rpg_vkr.domain.adventure import build_world

    session = hero(seed=1, profile="warrior", skills={"arcana": 1})
    value = world_value()
    # Existing catalog metadata, never an invented location at tick time.
    value["definitions"][0]["properties"]["home_id"] = "path"
    session.start_world(build_world(value, session, "synthetic-model"))
    return session


def test_generated_actor_uses_new_resolver_and_catalog_hp_and_replays():
    from rpg_vkr.domain.interactions import Step, WorldPlan

    session = generated()
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    before = next(e for e in session.catalog.entities if e.id == "watcher").state["hp"]
    turn = session.submit_actor_attempt(
        "атакую Морока", "watcher", "attack", False, "атака", "synthetic-model"
    )
    assert turn.gameplay and not turn.catalog
    after = next(e for e in session.catalog.entities if e.id == "watcher").state["hp"]
    assert after <= before
    assert turn.gameplay["result"]["attacks"]
    roundtrip(session)


def test_generated_merchant_copper_wallet_and_schedule_are_physical():
    session = generated()
    before = next(e for e in session.catalog.entities if e.id == "seller").state["gold_cp"]
    perform(session, "buy", merchant="seller", item="shop_seller_cloth")
    after = next(e for e in session.catalog.entities if e.id == "seller").state["gold_cp"]
    assert after == before + 30
    perform(session, "wait", minutes=14 * 60)
    ref = next(a for a in session.interactive_world.actor_refs if a.id == "seller")
    assert ref.place == "path"
    assert not session.actor_is_here("seller")
    roundtrip(session)


def test_ui_creation_and_equipment_are_real_commands(window, qt_app):
    from rpg_vkr.ui.creation_dialog import CreationDialog
    from rpg_vkr.ui.unified_panel import run

    dialog = CreationDialog()
    session = dialog.create_session()
    assert session.d20_progress is None
    window._session = session
    window._refresh_character()
    assert window.gameplay_group.isHidden() and not window.unified_group.isHidden()
    shield = next(i["id"] for i in session.gameplay["items"] if i["kind"] == "shield")
    run(window, "equip", {"item": shield})
    assert session.gameplay["shield"] == ""
    run(window, "equip", {"item": shield})
    assert session.gameplay["shield"] == shield
    assert "Снаряжение изменено" in window.unified_log.toPlainText()
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()
    dialog.close()


def test_initial_skill_draft_rejects_overspending_and_cancel_has_no_session_effect(qt_app):
    from PySide6.QtWidgets import QDialogButtonBox

    from rpg_vkr.ui.creation_dialog import CreationDialog

    dialog = CreationDialog()
    assert not hasattr(dialog, "initial_skills")
    for spin in dialog.scores.values():
        spin.setValue(16)
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    with pytest.raises(ValueError):
        dialog.create_session()
    dialog.reject()


def test_ordinary_actions_advance_world_clock_and_failure_rolls_everything_back(monkeypatch):
    import rpg_vkr.gameplay_session as boundary

    session = hero()
    before = session.gameplay["minute"]
    session.submit("идти на дорогу")
    assert session.gameplay["minute"] == before + 10
    session.submit_challenge("пытаюсь взобраться на стену")
    assert session.gameplay["minute"] == before + 11
    roundtrip(session)
    original, checkpoint = session.to_dict(), session.dice.checkpoint()
    monkeypatch.setattr(
        boundary, "finish_turn", lambda *args: (_ for _ in ()).throw(ValueError("tick failed"))
    )
    with pytest.raises(ValueError, match="tick failed"):
        session.submit("идти к воротам")
    assert session.to_dict() == original
    assert session.dice.checkpoint() == checkpoint


def test_catalog_projects_same_instances_and_exact_change_not_ghost_equipment():
    from rpg_vkr.storage.catalog import live_records

    session = hero()
    types, records = live_records(session)
    assert "legacy_equipment" not in records
    assert "legacy_book" not in records
    for value in session.gameplay["items"]:
        assert records[value["id"]]["owner_id"] == value["owner"]
        assert records[value["id"]]["state"]["durability"] == value["durability"]
    assert types["v3_type_dagger"]["properties"]["damage_dice"] == "1d4"


def test_level_five_rewards_and_circle_two_have_confirmed_campaign_sources():
    from test_adventure import world_value

    from rpg_vkr.domain.adventure import build_world

    session = hero(seed=1, profile="warrior", skills={"arcana": 2})
    value = world_value()
    value["definitions"].append(
        {
            "id": "tiny_type",
            "name": "Малый противник",
            "kind": "actor",
            "categories": ["creatures"],
            "properties": {"hp_max": 1, "strength": 1, "dexterity": 1},
        }
    )
    value["entities"].extend(
        {"id": f"tiny_{i}", "definition_id": "tiny_type", "parent_id": "pier"} for i in range(20)
    )
    session.start_world(build_world(value, session, "synthetic-model"))
    perform(session, "buy", merchant="seller", item="shop_seller_dagger")
    for i in range(20):
        if i == 10:
            perform(session, "equip", item="shop_seller_dagger")
        if i and i % 5 == 0:
            perform(session, "rest")
        for _ in range(20):
            actor = next(e for e in session.catalog.entities if e.id == f"tiny_{i}")
            if actor.state and actor.state.get("hp") == 0:
                break
            perform(session, "attack", target=f"tiny_{i}", lethal=0)
        assert not session.in_combat
    assert session.d20_progress.xp == 1000
    assert session.d20_progress.level == 5
    assert session.d20_progress.attribute_rewards == 1
    perform(session, "attribute", ability="strength")
    assert session.effective_character.strength == 17
    perform(session, "talent", talent="medic")
    perform(session, "talent", talent="scholar")
    perform(session, "learn", spell="flame")
    assert "flame" in session.gameplay["spells"]
    perform(session, "rest")
    from rpg_vkr.domain.interactions import Step, WorldPlan

    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    before_mp = session.gameplay["mp"]
    turn = perform(session, "cast", spell="flame", target="watcher")
    assert session.gameplay["mp"] == before_mp - 7
    assert "2d6" in turn.text
    roundtrip(session)


def test_new_campaign_window_opens_directly_with_persisted_gameplay(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from rpg_vkr.ui.main_window import MainWindow

    session = generated()
    widget = MainWindow(session=session, saves=SaveSlots(tmp_path / "slots"))
    widget.show()
    qt_app.processEvents()
    assert "MP" in widget.gameplay_status.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def test_collect_prepare_craft_has_no_duplicate_physical_material():
    from test_adventure import world_value

    from rpg_vkr.domain.adventure import build_world
    from rpg_vkr.domain.interactions import Step, WorldPlan

    session = hero(skills={"smithing": 1})
    value = world_value()
    value["entities"].append(
        {"id": "ore", "definition_id": "mat_iron", "parent_id": "pier", "quantity": 2}
    )
    session.start_world(build_world(value, session, "synthetic-model"))
    session.submit_interaction("беру железо", WorldPlan((Step("take", "ore", 2),)))
    for _ in range(2):
        perform(session, "prepare", item="ore")
    assert not any(t.id == "ore" for t in session.interaction_state().things)
    assert not any(e.id == "ore" for e in session.catalog.entities)
    before = len([i for i in session.gameplay["items"] if i["kind"] == "iron"])
    assert before == 4
    perform(session, "craft", recipe="dagger")
    assert len([i for i in session.gameplay["items"] if i["kind"] == "iron"]) == 2
    roundtrip(session)


def test_known_spell_with_insufficient_mp_has_no_rng_or_component_expense():
    session = hero(skills={"arcana": 1})
    perform(session, "learn", spell="light")
    for _ in range(8):
        perform(session, "cast", spell="light", target="hero")
    assert session.gameplay["mp"] == 0
    before, checkpoint = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="MP"):
        perform(session, "cast", spell="light", target="hero")
    assert session.to_dict() == before
    assert session.dice.checkpoint() == checkpoint


def test_lethal_outcome_and_observation_are_not_lost_in_legacy_actor_projection():
    session = hero(seed=1, profile="warrior")
    session.submit("идти на дорогу")
    for _ in range(20):
        if session.combat.actor("wolf").hp == 0:
            break
        perform(session, "attack", target="wolf", lethal=1)
    assert session.legacy_catalog_actor("wolf").state["life"] == "dead"
    assert session.gameplay["npc"]["boar"]["knowledge"][0]["kind"] == "personally_known"
    session.submit("идти к воротам")
    perform(session, "tell", target="guard", event="wolf")
    knowledge = session.gameplay["npc"]["guard"]["knowledge"]
    assert knowledge == [{"event": "wolf", "kind": "heard", "source": "hero", "confidence": 50}]
    assert session.gameplay["factions"]["local_witnesses"] == 1
    before = session.to_dict()
    with pytest.raises(ValueError):
        perform(session, "tell", target="guard", event="wolf")
    assert session.to_dict() == before
    roundtrip(session)


def test_attacking_merchant_closes_trade_contact_and_campaign_remains_loadable():
    session = hero(seed=1, profile="warrior")
    session.submit("узнать дорогу на рынок")
    session.submit("идти на рынок")
    session.submit("подойти к торговцу")
    assert session.world.trading
    session.submit("атаковать торговца")
    assert not session.world.trading
    roundtrip(session)


def test_standard_request_uuid_and_invalid_action_are_handled_before_commit():
    session = hero()
    id = "12345678-1234-1234-1234-123456789012"
    turn = session.perform_gameplay("wait", {"minutes": 1}, id)
    assert session.perform_gameplay("wait", {"minutes": 1}, id) is turn
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.perform_gameplay("wait", {"minutes": 1}, "next", action="x" * 501)
    assert session.to_dict() == before
    roundtrip(session)
