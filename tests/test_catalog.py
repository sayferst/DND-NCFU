"""The catalog is exercised with new objects, live legacy bindings and replay, without inference."""

import hashlib
import json
import random
import sqlite3
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog import CATEGORIES, Definition, Entity, seed_catalog
from rpg_vkr.domain.combat import CombatState
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.storage.catalog import CatalogIndex
from rpg_vkr.storage.knowledge import restore_session
from rpg_vkr.storage.slots import SaveSlots


def workshop(session, name="Дорожный кофр", *, locked=False):
    definitions = (
        Definition(
            "case_type",
            name,
            "item",
            ("miscellaneous",),
            {
                "container": True,
                "locked": locked,
                "open": not locked,
                "mass_g": 200,
                "volume_ml": 700,
                "capacity_ml": 400,
                "max_load_g": 1000,
            },
        ),
        Definition(
            "ingot_type",
            "Медная гиря",
            "item",
            ("materials",),
            {"portable": True, "mass_g": 600, "volume_ml": 200},
            materials=({"definition_id": "mat_copper", "parts": 1},),
        ),
        Definition(
            "artisan_type",
            "Мира",
            "actor",
            ("npcs",),
            {
                "hp_max": 6,
                "class": "artisan",
                "defence": 10,
                "goals": ["Закончить заказ до вечера"],
            },
        ),
    )
    entities = (
        Entity("case_one", "case_type", "gate"),
        Entity("ingots", "ingot_type", "gate", quantity=2),
        Entity(
            "mira",
            "artisan_type",
            "gate",
            state={"hp": 6, "gold_cp": 357, "secret": "Прячет письмо"},
        ),
    )
    session.register_catalog(
        "осмотрюсь в мастерской",
        definitions,
        entities,
        "В открытой мастерской видны кофр, гири и хозяйка.",
        "test-model",
    )
    return definitions, entities


def test_seed_has_ten_sections_materials_composition_and_effects_without_instances():
    catalog = seed_catalog()
    assert len(CATEGORIES) == 10 and len(catalog.definitions) == 46
    assert not catalog.entities
    s = Session(seed=5)
    before = s.to_dict(), s.dice.checkpoint()
    index = CatalogIndex(s)
    try:
        assert index.search("МЕДЬ", "materials")[0]["definition"]["id"] == "mat_copper"
        assert index.lookup("type_bandage")["definition"]["effects"][0]["magnitude"] == 4
        assert index.db.execute("SELECT count(*) FROM catalog_composition").fetchone()[0] > 10
        assert not index.db.execute("PRAGMA foreign_key_check").fetchall()
        assert index.lookup("not_a_real_id") is None
        assert index.lookup("'; DROP TABLE catalog_types;--") is None
        assert index.db.execute("SELECT count(*) FROM catalog_types").fetchone()[0] > 46
    finally:
        index.close()
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_live_legacy_inventory_and_private_actor_fields_are_not_independent_copies():
    s = Session(seed=5)
    s.submit("использовать бинт")
    index = CatalogIndex(s)
    try:
        assert index.lookup("legacy_bandages")["entity"]["quantity"] == s.world.bandages
        assert index.lookup("legacy_gold")["entity"]["quantity"] == s.world.gold
        assert "hp" not in index.lookup("guard")["entity"]["state"]
        assert index.lookup("merchant") is None
        assert index.lookup("merchant", public=False)["entity"]["state"]["gold_cp"] == 2000
    finally:
        index.close()


@pytest.mark.parametrize("name", ["Дорожный кофр", "Ларец с инкрустацией", "Текстильный чехол"])
def test_new_names_share_container_rules_and_keep_instance_identity(name, tmp_path):
    s = Session(seed=5)
    workshop(s, name)
    assert "Мира" in ";".join(build_frame(s).visible_actors)
    s.submit_interaction(
        "беру кофр и гири", WorldPlan((Step("take", "case_one"), Step("take", "ingots", 0)))
    )
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError, match="масса"):
        s.submit_interaction(
            "кладу обе гири внутрь", WorldPlan((Step("put", "ingots", 2, "case_one"),))
        )
    assert (s.to_dict(), s.dice.checkpoint()) == before
    s.submit_interaction(
        "кладу одну гирю внутрь", WorldPlan((Step("put", "ingots", 1, "case_one"),))
    )
    index = CatalogIndex(s)
    try:
        assert index.lookup("case_one")["definition"]["name"] == name
        rows = index.db.execute(
            "SELECT id,quantity FROM catalog_instances WHERE type_id='ingot_type'"
        ).fetchall()
        assert sum(q for _, q in rows) == 2 and len(rows) == 2
        assert index.lookup("mira", public=False)["entity"]["state"]["gold_cp"] == 357
        assert "gold_cp" not in index.lookup("mira")["entity"]["state"]
        assert "secret" not in index.lookup("mira")["entity"]["state"]
    finally:
        index.close()
    slots = SaveSlots(tmp_path)
    slots.save(1, s)
    restored = slots.load(1)
    assert restored.to_dict() == s.to_dict()
    assert restored.dice.checkpoint() == s.dice.checkpoint()


def test_locked_container_has_no_magic_access_and_failed_plan_preserves_state():
    s = Session(seed=5)
    workshop(s, locked=True)
    s.submit_interaction(
        "беру кофр и гири", WorldPlan((Step("take", "case_one"), Step("take", "ingots", 0)))
    )
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError, match="запертый"):
        s.submit_interaction(
            "кладу гирю в кофр", WorldPlan((Step("put", "ingots", 1, "case_one"),))
        )
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_catalog_items_are_not_silently_awarded_to_hero_or_overwritten():
    s = Session(seed=5)
    before = s.to_dict()
    with pytest.raises(ValueError, match="герою"):
        s.register_catalog(
            "Осмотрюсь",
            (),
            (Entity("free_sword", "type_knife", "hero"),),
            "Модель предлагает подарок",
            "test-model",
        )
    assert s.to_dict() == before
    workshop(s)
    before = s.to_dict()
    with pytest.raises(ValueError, match="перезаписать"):
        s.register_catalog(
            "Осмотрюсь",
            (Definition("case_type", "Другой кофр", "item", ("miscellaneous",), {}),),
            (),
            "Подмена",
            "test-model",
        )
    assert s.to_dict() == before


def test_boss_plant_loot_and_magic_descriptors_register_without_creating_loot():
    s = Session(seed=5)
    boss = Definition(
        "root_keeper",
        "Хранитель корней",
        "actor",
        ("plants", "creatures", "bosses"),
        {"hp_max": 50, "class": "guardian", "goals": ["Защитить рощу"]},
        rarity="unique",
        loot=({"definition_id": "mat_moon_ore", "min_qty": 1, "max_qty": 3, "chance_percent": 30},),
    )
    s.register_catalog(
        "вхожу в рощу",
        (boss,),
        (Entity("keeper_one", boss.id, "gate"),),
        "В роще показался её хранитель",
        "test-model",
    )
    index = CatalogIndex(s)
    try:
        assert len(index.search("", "bosses")) == 1
        assert index.lookup("keeper_one", public=False)["definition"]["loot"]
        assert index.lookup("keeper_one")["definition"]["loot"] == []
        assert (
            index.db.execute(
                "SELECT count(*) FROM catalog_instances WHERE type_id='mat_moon_ore'"
            ).fetchone()[0]
            == 0
        )
    finally:
        index.close()


def test_registered_actor_can_be_attacked_killed_and_replayed_without_a_moral_condition(tmp_path):
    s = Session(seed=5)
    workshop(s)
    for _ in range(2):
        turn = s.submit_actor_attempt(
            "хочу убить Миру", "mira", "attack", True, "Попытка нападения на Миру", "test-model"
        )
        assert turn.roll and turn.catalog.check.succeeded
    target = next(e for e in s.catalog.entities if e.id == "mira")
    assert target.state["hp"] == 0 and target.state["life"] == "dead"
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError, match="мертва"):
        s.submit_actor_attempt(
            "лечу Миру", "mira", "heal", False, "Обычная перевязка", "test-model"
        )
    assert (s.to_dict(), s.dice.checkpoint()) == before
    slots = SaveSlots(tmp_path)
    slots.save(1, s)
    restored = slots.load(1)
    assert restored.to_dict() == s.to_dict()
    assert restored.dice.roll_d20() == s.dice.roll_d20()


@pytest.mark.parametrize(
    "operation,text,field",
    [
        ("help", "помогаю Мире", "trust"),
        ("hinder", "мешаю Мире закончить дело", "grievance"),
        ("insult", "оскорбляю Миру", "grievance"),
    ],
)
def test_actor_influence_is_recorded_and_not_an_automatic_attack(operation, text, field):
    s = Session(seed=5)
    workshop(s)
    s.submit_actor_attempt(
        text, "mira", operation, False, "Проверяемая попытка влияния", "test-model"
    )
    target = next(e for e in s.catalog.entities if e.id == "mira")
    assert target.state["relations"]["hero"][field] == 1
    assert target.state["hp"] == 6
    assert s.combat.active is None
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_heal_legacy_actor_changes_one_real_bandage_and_actual_health():
    combat = CombatState()
    combat = combat.update(replace(combat.actor("guard"), hp=6))
    s = Session(seed=5, combat=combat)
    s.submit_actor_attempt(
        "перевязываю стражника",
        "guard",
        "heal",
        False,
        "Лечение живого раненого стражника",
        "test-model",
    )
    assert s.world.bandages == 0 and s.combat.actor("guard").hp == 10
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_lethal_finishing_attempt_on_a_defeated_legacy_actor_is_a_checked_event():
    combat = CombatState()
    combat = combat.update(replace(combat.actor("guard"), hp=0))
    s = Session(seed=5, combat=combat)
    s.submit_actor_attempt(
        "добиваю стражника", "guard", "attack", True, "Смертельное нападение", "test-model"
    )
    assert s.turns[-1].catalog.entity_after.state["life"] == "dead"
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


@pytest.mark.parametrize(
    "text", ["не хочу убивать Миру", "можно ли убить Миру?", "если убить Миру"]
)
def test_questions_negations_and_hypotheses_are_not_attacks(text):
    s = Session(seed=5)
    workshop(s)
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        s.submit_actor_attempt(text, "mira", "attack", True, "Попытка", "test-model")
    assert (s.to_dict(), s.dice.checkpoint()) == before


@pytest.mark.parametrize("damage", ["catalog", "record", "quantity", "attempt"])
def test_tampered_catalog_and_actor_consequences_are_rejected(damage):
    s = Session(seed=5)
    workshop(s)
    s.submit_actor_attempt("атакую Миру", "mira", "attack", False, "Атака", "test-model")
    data = deepcopy(s.to_dict())
    if damage == "catalog":
        data["catalog"]["entities"][2]["state"]["hp"] = 100
    elif damage == "record":
        data["turns"][0]["catalog"]["entities"][0]["parent_id"] = "hero"
    elif damage == "quantity":
        data["interactive_world"]["things"][-1]["quantity"] = 99
    else:
        data["turns"][1]["catalog"]["entity_after"]["state"]["hp"] = 5
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_sqlite_export_roundtrip_and_safe_working_publication(tmp_path, monkeypatch):
    s = Session(seed=5)
    workshop(s)
    index = CatalogIndex(s)
    try:
        path = tmp_path / "world.sqlite3"
        index.export(path)
        assert restore_session(path).to_dict() == s.to_dict()
        with pytest.raises(FileExistsError):
            index.export(path)
        working = tmp_path / "working.sqlite3"
        index.publish(working)
        previous = working.read_bytes()
        index.publish(working)
        assert working.read_bytes() == previous
        foreign = tmp_path / "foreign.sqlite3"
        with sqlite3.connect(foreign) as db:
            db.execute("CREATE TABLE keep_me(value TEXT)")
        original = foreign.read_bytes()
        with pytest.raises(ValueError, match="другая база"):
            index.publish(foreign)
        assert foreign.read_bytes() == original

        def fail(*_):
            raise OSError("simulated disk failure")

        monkeypatch.setattr("rpg_vkr.storage.catalog.os.replace", fail)
        with pytest.raises(OSError):
            index.publish(working)
        assert working.read_bytes() == previous
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        index.close()


def test_real_v18_migration_preserves_old_world_and_rng_without_rewriting_source(tmp_path):
    root = Path(__file__).parent / "fixtures"
    raw = (root / "save-v18.json").read_bytes()
    source = json.loads((root / "save-v18.source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    (tmp_path / "slot-1.json").write_bytes(raw)
    slots = SaveSlots(tmp_path)
    s = slots.load(1)
    assert s.catalog is None and s.current_place_id == "forest"
    checkpoint = s.dice.checkpoint()
    slots.save(2, s)
    restored = slots.load(2)
    assert restored.to_dict() == s.to_dict()
    assert restored.dice.checkpoint() == checkpoint
    assert restored.dice.roll_d20() == s.dice.roll_d20()
    assert (tmp_path / "slot-1.json").read_bytes() == raw


def test_generated_sizes_and_new_ids_obey_capacity_without_named_object_conditions():
    rng = random.Random(19)
    for i in range(25):
        volume, mass = rng.randint(1, 1000), rng.randint(1, 1000)
        capacity, max_mass = rng.randint(1, 1000), rng.randint(1, 1000)
        s = Session(seed=i)
        defs = (
            Definition(
                f"vessel_type_{i}",
                f"Сосуд {i}",
                "item",
                ("miscellaneous",),
                {"container": True, "capacity_ml": capacity, "max_load_g": max_mass},
            ),
            Definition(
                f"cargo_type_{i}",
                f"Груз {i}",
                "item",
                ("miscellaneous",),
                {"mass_g": mass, "volume_ml": volume},
            ),
        )
        s.register_catalog(
            "осматриваю мастерскую",
            defs,
            (Entity("vessel", defs[0].id, "gate"), Entity("cargo", defs[1].id, "gate")),
            "Предметы видны в мастерской",
            "test-model",
        )
        s.submit_interaction(
            "беру сосуд и груз", WorldPlan((Step("take", "vessel"), Step("take", "cargo")))
        )
        before = s.to_dict(), s.dice.checkpoint()
        if volume <= capacity and mass <= max_mass:
            s.submit_interaction(
                "кладу груз в сосуд", WorldPlan((Step("put", "cargo", 1, "vessel"),))
            )
            assert next(t for t in s.interactive_world.things if t.id == "cargo").holder == "vessel"
            assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()
        else:
            with pytest.raises(ValueError, match="превышена"):
                s.submit_interaction(
                    "кладу груз в сосуд", WorldPlan((Step("put", "cargo", 1, "vessel"),))
                )
            assert (s.to_dict(), s.dice.checkpoint()) == before


def test_remote_actor_is_not_reached_and_non_action_negation_does_not_block_attack():
    s = Session(seed=5)
    workshop(s)
    s.submit_actor_attempt(
        "не сомневаясь, атакую Миру", "mira", "attack", False, "Атака", "test-model"
    )
    s.submit_interaction("иду на дорогу", WorldPlan((Step("move", "road"),)))
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError, match="нет рядом"):
        s.submit_actor_attempt("атакую Миру", "mira", "attack", False, "Атака", "test-model")
    assert (s.to_dict(), s.dice.checkpoint()) == before
    assert not any("Мира" in actor for actor in build_frame(s).visible_actors)


@pytest.mark.parametrize("text", ["Я не собираюсь его убивать", "Говорю Мире: убью тебя"])
def test_negative_intent_and_threatened_speech_cannot_become_physical_attack(text):
    s = Session(seed=5)
    workshop(s)
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        s.submit_actor_attempt(
            text, "mira", "attack", True, "Атака", "test-model", confirmed_intent=True
        )
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_failed_bandaging_consumes_one_real_bandage_and_does_not_invent_healing():
    combat = CombatState().update(replace(CombatState().actor("guard"), hp=6))
    s = Session(seed=2, combat=combat)
    turn = s.submit_actor_attempt(
        "перевязываю стражника", "guard", "heal", False, "Перевязка", "test-model"
    )
    assert not turn.check.succeeded and s.combat.actor("guard").hp == 6
    assert s.world.bandages == 0 and s.dice.checkpoint()[1] == 1
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_new_material_changes_armour_properties_and_actual_attack_difficulty():
    material = Definition(
        "mat_stariron",
        "Звёздное железо",
        "material",
        ("materials",),
        {"equipment_modifiers": {"defence": 4, "penetration": 2, "durability": 20}},
    )
    armour = Definition(
        "star_armour",
        "Броня звёздного железа",
        "item",
        ("armour",),
        {"defence": 1, "durability": 30},
        materials=(
            {"definition_id": "mat_stariron", "parts": 3},
            {"definition_id": "mat_iron", "parts": 1},
        ),
    )
    actor = Definition(
        "star_guard",
        "Звёздный хранитель",
        "actor",
        ("creatures",),
        {"hp_max": 8, "defence": 10},
        materials=({"definition_id": "mat_stariron", "parts": 1},),
    )
    s = Session(seed=7)
    s.register_catalog(
        "осмотрюсь",
        (material, armour, actor),
        (Entity("guardian", "star_guard", "gate"),),
        "В мастерской виден механический хранитель.",
        "test-model",
    )
    index = CatalogIndex(s)
    try:
        computed = index.lookup("star_armour")["derived_properties"]
        assert computed["defence"] == 4 and computed["durability"] == 45
    finally:
        index.close()
    turn = s.submit_actor_attempt(
        "атакую хранителя",
        "guardian",
        "attack",
        False,
        "Атака по защищённому корпусу",
        "test-model",
    )
    assert turn.roll.value == 11 and turn.check.total == 13
    assert turn.check.difficulty == 14 and not turn.check.succeeded
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_failed_finishing_attempt_does_not_turn_defeat_into_death():
    combat = CombatState().update(replace(CombatState().actor("guard"), hp=0))
    s = Session(seed=2, combat=combat)
    turn = s.submit_actor_attempt(
        "добиваю стражника", "guard", "attack", True, "Смертельное нападение", "test-model"
    )
    assert not turn.check.succeeded
    assert turn.catalog.entity_after.state["life"] == "defeated"
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_confirmed_dead_actor_can_be_described_later_but_cannot_speak():
    from rpg_vkr.narrative.story_quality import check_story_quality

    s = Session(seed=5)
    workshop(s)
    for _ in range(2):
        s.submit_actor_attempt("убить Миру", "mira", "attack", True, "Атака", "test-model")
    frame = build_frame(s)
    check_story_quality(
        "Мира погибла. В мастерской тихо, инструменты остались на столе.", frame, "Что я вижу?"
    )
    with pytest.raises(ValueError, match="Погибший"):
        check_story_quality(
            "Мира говорит: «Оставьте мои инструменты на месте». Это звучит тихо.",
            frame,
            "Что я вижу?",
        )
