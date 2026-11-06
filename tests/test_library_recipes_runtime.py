"""Finite owned materials, equipment integration, atomic crafting and exact replay."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog import Definition, Entity, Registration
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.model import ROOT, read_jsonl
from rpg_vkr.world_library.physical_rules import PROFILES, compile_physical
from rpg_vkr.world_library.recipe_rules import compile_recipe
from rpg_vkr.world_library.store import Library


@pytest.fixture(scope="module")
def records():
    return read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")


@pytest.fixture
def library(tmp_path, records):
    db = Library.sqlite(tmp_path / "library.sqlite3")
    db.migrate()
    db.import_records(records)
    yield db
    db.close()


def take(session, id):
    session.perform_gameplay(
        "attempt",
        {
            "version": 1,
            "plan": {
                "operation": "take",
                "goal": "",
                "items": [id],
                "tool": "",
            },
        },
        "take-" + id,
    )


def test_all_original_physical_objects_and_720_recipes_compile(records):
    definitions = {}
    for row in records:
        if row["profile"] in PROFILES:
            rules = compile_physical(row)
            assert rules["quality"] == row["attributes"]["quality"]
            definitions[row["id"]] = Definition(
                row["id"],
                row["name"],
                "item",
                ("miscellaneous",),
                {"library_item_rules": rules},
            )
    recipes = [r for r in records if r["profile"] == "recipe"]
    assert len(recipes) == 720
    for row in recipes:
        links = [
            {
                "definition": link["target"],
                "relation": link["relation"],
                "quantity": link["quantity"],
            }
            for link in row["links"]
        ]
        compile_recipe(row, links, definitions)


def setup_recipe(library):
    session = campaign(hp=12)
    proposal = preview(library, session, "wl_recipe_weapon_0_0", "recipe_card")
    commit(session, proposal)
    take(session, "recipe_card")
    for index, (template, instance) in enumerate(
        [
            ("wl_tool_1_0", "smith_tools"),
            ("wl_material_9", "metal_stock"),
            ("wl_material_0", "wood_stock"),
        ]
    ):
        proposal = preview(library, session, template, instance)
        if index:
            proposal = replace(proposal, entities=(replace(proposal.entities[0], quantity=2),))
        commit(session, proposal)
        take(session, instance)
    return session


def add_forge(session):
    scene = session.interaction_state()
    record = Registration(
        (
            Definition(
                "library_test_forge_type",
                "Проверочная кузница",
                "item",
                ("miscellaneous",),
                {"station": "forge", "public": True},
            ),
        ),
        (Entity("library_test_forge", "library_test_forge_type", scene.current),),
        "Проверочный рабочий стенд",
        "test-engine",
        len(session.turns),
        scene,
    )
    commit(session, record)


def test_recipe_station_materials_and_rng_rejection_are_atomic(library):
    session = setup_recipe(library)
    before = session.to_dict()
    checkpoint = session.dice.checkpoint()
    with pytest.raises(ValueError, match="forge"):
        session.perform_gameplay("library_recipe", {"item": "recipe_card"}, "missing-forge")
    assert session.to_dict() == before and session.dice.checkpoint() == checkpoint
    add_forge(session)
    before_minute = session.gameplay["minute"]
    session.perform_gameplay("library_recipe", {"item": "recipe_card"}, "craft-sword")
    by_id = {e.id: e for e in session.catalog.entities}
    assert by_id["metal_stock"].quantity == by_id["wood_stock"].quantity == 1
    assert session.gameplay["minute"] >= before_minute + 60
    restored = Session.from_dict(session.to_dict(), version=31)
    assert restored.to_dict() == session.to_dict()
    assert restored.dice.checkpoint() == session.dice.checkpoint()
    # A second attempt can consume the last units, never regenerate them on reload.
    session.perform_gameplay("library_recipe", {"item": "recipe_card"}, "craft-sword-2")
    assert not {"metal_stock", "wood_stock"} & {e.id for e in session.catalog.entities}
    before = session.to_dict()
    with pytest.raises(ValueError, match="material"):
        session.perform_gameplay("library_recipe", {"item": "recipe_card"}, "no-materials")
    assert session.to_dict() == before
    assert Session.from_dict(before, version=31).to_dict() == before


def test_homebrew_bow_requires_its_own_ammunition_and_equips(library):
    session = campaign(hp=12)
    commit(session, preview(library, session, "wl_weapon_10_0", "original_bow"))
    take(session, "original_bow")
    session.perform_gameplay("equip", {"item": "original_bow"}, "equip-original-bow")
    assert session.gameplay["weapon"] == "original_bow"
    from rpg_vkr.domain.catalog_engine import Engine
    from rpg_vkr.unified_session import context

    engine = Engine(session.gameplay, context(session), session.dice, {})
    row = engine.template(engine.owned("original_bow"))
    assert row["required_ammunition"] == "arrow"
    assert row["quality"] == library.get("wl_weapon_10_0")["attributes"]["quality"]
    assert Session.from_dict(session.to_dict(), version=31).to_dict() == session.to_dict()


def test_recipe_program_rejects_unknown_operations_before_execution():
    from rpg_vkr.world_library.recipe_rules import validate

    rules = {
        "version": "library-recipe-1",
        "labour_cp": 0,
        "minutes": 30,
        "difficulty": 10,
        "mode": "salvage",
        "station": "workbench",
        "inputs": [{"definition": "input", "quantity": 1}],
        "outputs": [{"definition": "output", "quantity": 1}],
    }
    validate(rules)
    for field, value in (("sql", "DELETE FROM saves"), ("minutes", True)):
        bad = deepcopy(rules)
        bad[field] = value
        with pytest.raises(ValueError):
            validate(bad)
