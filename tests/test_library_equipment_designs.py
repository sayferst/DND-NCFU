"""Original designs have typed provenance and refer to existing canonical materials."""

from test_library_utility_runtime import library  # noqa: F401
from test_owner_rules_runtime import campaign

from rpg_vkr.world_library.bridge import preview
from rpg_vkr.world_library.equipment_rules import compile_equipment, pending_features
from rpg_vkr.world_library.model import equipment_records
from rpg_vkr.world_library.presentation import card


def test_source_bow_has_distinct_wood_string_and_grip_in_real_engine_definition(
    library,  # noqa: F811
):
    rows = equipment_records()
    library.import_records(rows)
    row = next(r for r in rows if r["attributes"]["source_name"] == "Короткий лук")
    proposal = preview(library, campaign(hp=12), row["id"], "source_bow")
    definition = next(d for d in proposal.definitions if d.id == row["id"])
    assert {part["definition_id"] for part in definition.materials} == {
        "wl_material_1",
        "wl_material_5",
        "wl_material_6",
    }
    assert row["attributes"]["design_origin"] == "invented/homebrew"
    assert "тетива" in card(row)["appearance"]
    assert "Местное производство" not in row["attributes"]["history_homebrew"]


def test_buckler_and_gladiator_armours_are_not_household_objects():
    rows = equipment_records()
    buckler = next(r for r in rows if r["attributes"]["source_name"] == "Баклер")
    rules = compile_equipment(buckler)
    assert rules["kind"] == "armour" and rules["category"] == "shield" and rules["defence"] == 1
    for row in rows:
        if row["attributes"]["section"] == "Доспехи":
            assert compile_equipment(row)["kind"] == "armour"
        assert row["attributes"]["appearance_homebrew"]
        assert row["attributes"]["purpose_homebrew"]


def test_source_special_property_is_visible_as_pending_until_its_handler_exists():
    row = next(r for r in equipment_records() if r["attributes"]["source_name"] == "Сеть")
    assert pending_features(row)
    assert card(row)["mechanics"]["pending_features"] == pending_features(row)
