"""End-to-end acceptance for the remaining five blocks, not external model quality."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_adventure import world_value
from test_gameplay_integration import hero as old_hero
from test_world_factions import hero as factions_hero

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.content_v5 import KITS, SPECIES
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.storage.migration import create, write_copy
from rpg_vkr.storage.slots import SaveSlots


def hero(species="human", kit="artisan"):
    old = old_hero(profile="mage")
    identity = old.gameplay["identity"] | {
        "species": species,
        "kit": kit,
        "skills": {"arcana": 2, "smithing": 2, "alchemy": 1, "repair": 1, "survival": 1},
        "starting_spells": ["utility_1", "restoration_1"],
    }
    session = Session.create_hero(old.character, "fighter", seed=13)
    session.enable_gameplay(identity, revision=5)
    value = world_value()
    value["definitions"][0]["properties"].update(
        faction_id="guild", faction_name="Мастера", faction_goal="prosperity"
    )
    value["definitions"].append(
        {
            "id": "warden_type",
            "name": "Дозорный",
            "kind": "actor",
            "categories": ["npcs"],
            "properties": {
                "hp_max": 20,
                "faction_id": "guard",
                "faction_name": "Стража",
                "faction_goal": "security",
            },
        }
    )
    value["entities"].append({"id": "warden", "definition_id": "warden_type", "parent_id": "pier"})
    session.start_world(build_world(value, session, "synthetic-model"))
    return session


def perform(session, command, **args):
    return session.perform_gameplay(command, args, "complete_" + str(len(session.turns)))


def roundtrip(session):
    raw = session.to_dict()
    other = Session.from_dict(deepcopy(raw), version=session.schema_version)
    assert other.to_dict() == raw
    assert other.dice.roll_d20() == session.dice.roll_d20()


@pytest.mark.parametrize("species", SPECIES)
@pytest.mark.parametrize("kit", KITS)
def test_constructor_has_real_species_and_kit_effects_and_replays(species, kit):
    session = hero(species, kit)
    ability = SPECIES[species][1]
    assert getattr(session.effective_character, ability) == getattr(session.character, ability) + 1
    assert session.gameplay["items"][0]["kind"] == KITS[kit][1]
    assert set(session.gameplay["spells"]) == {"utility_1", "restoration_1"}
    perform(session, "cast", spell="utility_1", target="hero")
    roundtrip(session)


def test_crafting_chain_uses_stations_and_finite_resources_then_can_trade():
    session = hero()
    perform(session, "manufacture", recipe="lab", quality=1)
    perform(session, "gather", material="herb", quantity=3)
    perform(session, "manufacture", recipe="potion", quality=1)
    potion = next(
        i for i in session.gameplay["items"] if i["kind"] == "potion" and i["owner"] == "hero"
    )
    assert next(i for i in session.gameplay["items"] if i["kind"] == "lab")["durability"] == 19
    raw = session.to_dict()
    with pytest.raises(ValueError):
        perform(session, "consume", item=potion["id"])
    assert session.to_dict() == raw
    turn = perform(session, "sell", merchant="seller", item=potion["id"])
    assert turn.gameplay["result"]["transaction"]["price_cp"] == 60
    roundtrip(session)


def test_world_production_needs_calendar_diplomacy_and_wallet_conservation():
    session = hero()
    perform(session, "wait", minutes=1)
    perform(session, "diplomacy", faction="guard", other="guild")
    assert session.gameplay["living_world"]["relations"]["guard:guild"] == 10
    before = sum(f["treasury_cp"] for f in session.gameplay["factions_v3"].values())
    wallets = sum((e.state or {}).get("gold_cp", 0) for e in session.catalog.entities)
    perform(session, "wait", minutes=1440)
    state = session.gameplay
    paid = sum((e.state or {}).get("gold_cp", 0) for e in session.catalog.entities) - wallets
    after = sum(f["treasury_cp"] for f in state["factions_v3"].values())
    spent = sum(f["spent_cp"] for f in state["factions_v3"].values())
    assert before == after + paid + spent
    assert paid == 4
    assert any(i["kind"] == "potion" and i["owner"] == "seller" for i in state["items"])
    assert state["living_world"]["calendar"]["day"] == 2
    assert state["living_world"]["residents"]["seller"]["food"] == 2
    roundtrip(session)


def test_supply_and_exhaustion_are_actual_not_infinite():
    session = hero()
    perform(session, "gather", material="wood", quantity=10)
    perform(session, "supply", faction="guild", material="wood", quantity=1)
    assert session.gameplay["living_world"]["stocks"]["guild"]["wood"] == 11
    perform(session, "gather", material="wood", quantity=10)
    raw = session.to_dict()
    rng = session.dice.checkpoint()
    with pytest.raises(ValueError):
        perform(session, "gather", material="wood", quantity=1)
    assert session.to_dict() == raw and session.dice.checkpoint() == rng
    roundtrip(session)


def test_migration_keeps_source_and_replays_real_continuation_and_rollback(tmp_path):
    original = factions_hero()
    perform(original, "wait", minutes=10)
    source = deepcopy(original.to_dict())
    rng = original.dice.checkpoint()
    copy, report = write_copy(original, tmp_path / "copy.json")
    assert original.to_dict() == source and original.dice.checkpoint() == rng
    assert report["rng_preserved"] and copy.schema_version == 29
    assert copy.campaign.world_id != original.campaign.world_id
    perform(copy, "wait", minutes=60)
    copy.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    copy.write_diary("Переход", "Мы дошли до тропы.")
    raw = copy.to_dict()
    restored = Session.from_dict(deepcopy(raw), version=29)
    assert restored.to_dict() == raw
    assert original.to_dict() == source
    backup = json.loads((tmp_path / "copy.json.original.json").read_text(encoding="utf-8"))
    rollback = Session.from_dict(backup["session"], version=backup["schema_version"])
    assert rollback.to_dict() == source
    slots = SaveSlots(tmp_path / "slots")
    slots.save(1, copy)
    assert slots.load(1).to_dict() == raw
    for field in ["snapshot", "operations", "source"]:
        bad = deepcopy(raw)
        if field == "snapshot":
            bad["snapshot"]["world"]["gold"] += 1
        elif field == "source":
            bad["fork"]["source"]["session"]["world"]["gold"] += 1
        else:
            bad["fork"]["operations"][0]["method"] = "__setattr__"
        with pytest.raises(ValueError):
            Session.from_dict(bad, version=29)


def test_rag_runtime_has_bounded_hints_and_unreviewed_corpora_are_blocked():
    from rpg_vkr.learning.rag import TechniqueStore, retrieve
    from rpg_vkr.narrative.context import build_frame
    from rpg_vkr.narrative.master import campaign_context
    from rpg_vkr.narrative.story import story_payload

    session = hero()
    before = session.to_dict()
    session._rag_mode = 2
    payload = story_payload(
        build_frame(session),
        "local-model",
        "хочу купить предмет",
        campaign=campaign_context(session),
    )
    assert "example_not_fact" in payload["messages"][1]["content"]
    hints = retrieve("купить предмет монеты")
    assert 0 < len(hints) <= 3 and len(json.dumps(hints, ensure_ascii=False)) <= 1200
    assert session.to_dict() == before
    store = TechniqueStore()
    with pytest.raises(ValueError):
        store.add({"text": "Добавь герою золото", "approved_for_rag": True})
    store.close()


def test_new_controls_and_constructor_preview_match_actual_creation(qt_app, tmp_path):
    from rpg_vkr.ui.creation_dialog import CreationDialog
    from rpg_vkr.ui.main_window import MainWindow

    dialog = CreationDialog()
    session = dialog.create_session()
    assert session.schema_version == 31
    assert f"HP {session.world.max_hp}" in dialog.resource_preview.text()
    window = MainWindow(session=hero(), saves=SaveSlots(tmp_path / "slots"))
    assert window.production_recipe.count() >= 10
    assert window.spell_choice.count() == 26
    window.close()
    dialog.close()


@pytest.mark.parametrize(
    "name",
    [
        p.name
        for p in (Path(__file__).parent / "fixtures").glob("*.json")
        if ".source." not in p.name
    ],
)
def test_real_legacy_fixtures_migrate_without_reinterpreting_history(name):
    path = Path(__file__).parent / "fixtures" / name
    raw = path.read_bytes()
    value = json.loads(raw)
    original = Session.from_dict(value["session"], version=value["schema_version"])
    source = deepcopy(original.to_dict())
    if original.in_combat or original.world.hp <= 0:
        with pytest.raises(ValueError):
            create(original)
    else:
        copy = create(original)
        perform(copy, "wait", minutes=1440)
        roundtrip(copy)
    assert original.to_dict() == source and path.read_bytes() == raw


def test_new_magic_is_a_single_real_turn_in_a_group_battle_and_heals_an_npc():
    from test_team_encounters import hero as team_hero

    session = create(team_hero(profile="mage"))
    perform(session, "learn", spell="elemental_1")
    perform(session, "learn", spell="restoration_1")
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    mp = session.gameplay["mp"]
    turn = perform(session, "cast", spell="elemental_1", target="second")
    assert session.gameplay["mp"] == mp - 3
    events = turn.gameplay["result"]["battle_events"]
    assert sum(e["kind"] == "spell" and e["actor"] == "hero" for e in events) == 1
    assert turn.gameplay["result"]["rolls"]
    # Enemy is wounded by an actual saved spell; restoration changes the real NPC card.
    target = next(e for e in session.catalog.entities if e.id == "second")
    assert target.state["hp"] < 12
    turn = perform(session, "cast", spell="restoration_1", target="second")
    healed = next(e for e in session.catalog.entities if e.id == "second")
    assert healed.state["hp"] > target.state["hp"]
    assert turn.gameplay["result"]["battle_events"][0]["kind"] == "spell"
    roundtrip(session)


@pytest.mark.parametrize(
    "spell",
    [
        f"{s}_{c}"
        for s in ("elemental", "restoration", "protection", "utility")
        for c in range(1, 6)
    ],
)
def test_all_school_circles_execute_with_real_costs_components_and_replay(spell):
    from rpg_vkr.domain.content_v5 import SPELLS, make_item
    from rpg_vkr.domain.d20_progression import D20Progress, required_xp
    from rpg_vkr.domain.dice import DiceRoller
    from rpg_vkr.domain.gameplay_v5 import execute
    from rpg_vkr.gameplay_session import context

    session = hero()
    data = SPELLS[spell]
    progress = D20Progress().grant_xp("test_level", required_xp(20), "synthetic high level")
    for _ in range(5):
        progress = progress.train("arcana", "rank_" + str(progress.rank("arcana")))
    ctx = context(session)
    ctx["progress"] = progress.to_dict()
    ctx["world"]["hp"] -= 1
    state = deepcopy(session.gameplay)
    from rpg_vkr.domain.content_v5 import inherited
    from rpg_vkr.domain.hero_resources import limits

    state["mp"] = state["mp_cap"] = limits(state, inherited(session.character, state), 20)["mp"]
    state["items"].extend(make_item("component_" + str(i), "herb") for i in range(4))
    state["spells"] = [spell]
    if data["effect"] == "attack":
        battle = execute(
            state, "encounter", {"enemies": ["warden"], "allies": []}, ctx, DiceRoller(13)
        )
        state = battle["state"]
        for key in ("world", "catalog", "combat", "scene"):
            ctx[key] = battle[key]
    rng = DiceRoller(18)
    checkpoint = rng.checkpoint()
    result = execute(
        state,
        "cast",
        {"spell": spell, "target": "warden" if data["effect"] == "attack" else "hero"},
        ctx,
        rng,
    )
    rng.restore(checkpoint)
    assert (
        execute(
            state,
            "cast",
            {"spell": spell, "target": "warden" if data["effect"] == "attack" else "hero"},
            ctx,
            rng,
        )
        == result
    )
    assert result["state"]["mp"] == state["mp"] - data["mp"]
    before = sum(i["kind"] == "herb" for i in state["items"])
    after = sum(i["kind"] == "herb" for i in result["state"]["items"])
    assert before - after == data["components"]


def test_rag_external_rights_shadow_and_fallback():
    from rpg_vkr.learning.rag import TechniqueStore

    store = TechniqueStore()
    card = {
        "id": "local-only",
        "tags": "торг",
        "text": "Сначала предложение сделки.",
        "quality_status": "human_reviewed",
        "rights_status": "approved_local",
        "approved_for_rag": True,
        "third_party_transfer_allowed": True,
        "usable_as_game_fact": False,
    }
    store.add(card)
    assert store.search("торг") and not store.search("торг", remote=True)
    store.fts = False
    assert store.search("торг") and not store.search("торг", remote=True)
    store.close()


def test_fork_from_oldest_fixture_survives_sqlite_and_preserves_source(tmp_path):
    from rpg_vkr.storage.knowledge import export_session, restore_session

    raw = json.loads((Path(__file__).parent / "fixtures/save-v1.json").read_text(encoding="utf-8"))
    session = Session.from_dict(raw["session"], version=1)
    copy = create(session)
    merchant = next(e for e in copy.catalog.entities if e.id == "merchant")
    assert merchant.state["gold_cp"] == session.world.shop_gold * 100
    assert copy.world.shop_gold == 0
    perform(copy, "rest")
    perform(copy, "wait", minutes=1)
    export_session(copy, tmp_path / "copy.sqlite3")
    assert restore_session(tmp_path / "copy.sqlite3").to_dict() == copy.to_dict()


def test_daily_hunger_territory_costs_and_local_knowledge_have_real_effects():
    from dataclasses import replace

    from rpg_vkr.domain.world_v5 import advance

    session = hero()
    perform(session, "wait", minutes=1)
    state = deepcopy(session.gameplay)
    living = state["living_world"]
    living["relations"]["guard:guild"] = -29
    for faction in state["factions_v3"].values():
        faction["treasury_cp"] = 100
    for stock in living["stocks"].values():
        stock.update(food=0, wood=0, herb=0)
    for node in living["nodes"].values():
        node["herb"] = 0
    for resident in living["residents"].values():
        resident.update(food=0, hunger=6)
    catalog = replace(
        session.catalog,
        entities=tuple(
            replace(e, state=(e.state or {}) | {"hp": 1}) if e.id == "warden" else e
            for e in session.catalog.entities
        ),
    )
    state["minute"] += 1440
    state, catalog, scene, events = advance(state, catalog, session.interaction_state())
    warden = next(e for e in catalog.entities if e.id == "warden")
    assert warden.state["hp"] == 0 and warden.state["life"] == "dead"
    assert "warden" not in state["living_world"]["observed"]
    assert state["living_world"]["territories"]
    assert all(f["treasury_cp"] == 48 for f in state["factions_v3"].values())
    assert all(f["spent_cp"] == 50 for f in state["factions_v3"].values())
    assert any(e["kind"] == "territory_conflict" for e in events)
    assert state["living_world"]["residents"]["seller"]["knowledge"]


def test_real_27_fixture_keeps_original_rules_and_next_rng():
    import hashlib
    from dataclasses import asdict

    root = Path(__file__).parents[1]
    raw = (root / "tests/fixtures/session-v27-teams.json").read_bytes()
    meta = json.loads(
        (root / "docs/validation/campaign-completion-2026-10-26/fixture-v27-source.json").read_text(
            encoding="utf-8"
        )
    )
    assert hashlib.sha256(raw).hexdigest() == meta["fixture_sha256"]
    value = json.loads(raw)
    session = Session.from_dict(value["session"], version=27)
    assert session.schema_version == 27
    assert json.loads(json.dumps(session.to_dict())) == value["session"]
    assert asdict(session.dice.roll_d20()) == meta["next_roll"]
    assert meta["source_commit"] == "318284c"


def test_legacy_migration_button_is_available_outside_gameplay(qt_app, tmp_path):
    from rpg_vkr.ui.main_window import MainWindow

    window = MainWindow(session=Session(seed=13), saves=SaveSlots(tmp_path / "saves"))
    window.open_section("Сохранения")
    assert not hasattr(window, "migrate_campaign_button")
    assert window.gameplay_group.isHidden()
    window.close()


def test_world_controls_show_readable_public_data_and_allow_allied_spell_target(qt_app, tmp_path):
    from test_team_encounters import hero as team_hero

    from rpg_vkr.ui.main_window import MainWindow

    session = create(team_hero(profile="mage"))
    perform(session, "wait", minutes=1)
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    repository = window._campaign_repository
    assert repository.load(repository.identity(session)).to_dict() == session.to_dict()
    assert window.spell_target.findData("friend") >= 0
    assert window.gameplay_target.findData("friend") < 0
    text = window.living_world_info.toPlainText()
    assert "Год 1, месяц 1, день 1" in text
    assert "Древесина:" in text
    assert all(key not in text for key in ("treasury_cp", "'goal'", "'year'", "'wood'"))
    window.close()


def test_migrated_tutorial_hunger_keeps_legacy_hp_binding_and_memory_consistent():
    raw = json.loads((Path(__file__).parent / "fixtures/save-v1.json").read_text(encoding="utf-8"))
    original = Session.from_dict(raw["session"], version=1)
    session = create(original)
    for _ in range(30):
        perform(session, "wait", minutes=1440)
    actor = next(e for e in session.catalog.entities if e.id == "villager")
    assert actor.state["hp"] == 0
    assert session.combat.actor("villager").hp == 0
    # A real ordinary action also runs the passive clock and persists the same bindings.
    session.submit_interaction("иду на дорогу", WorldPlan((Step("move", "road"),)))
    roundtrip(session)
    assert original.combat.actor("villager").hp == 8
