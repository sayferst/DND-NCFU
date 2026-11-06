"""Source parameter extraction, stable identities, graph integrity and safe regeneration."""

import json
import sys
from collections import Counter
from copy import deepcopy
from urllib.parse import unquote

import pytest

from rpg_vkr.world_library.model import ROOT, read_jsonl, validate_bundle, validate_record

sys.path.insert(0, str(ROOT / "scripts"))
from enrich_rpgd100_references import (  # noqa: E402
    CardSurface,
    catalog_records,
    html_sections,
    magic_details,
    name_keys,
    other_details,
    race_details,
    source_bool,
    spell_details,
    table_calls,
)
from import_rpgd100_facts import literal_array  # noqa: E402
from import_rpgd100_index import preserve_details  # noqa: E402


@pytest.fixture(scope="module")
def references():
    return read_jsonl(ROOT / "data/world_library/rpgd100-reference-index.jsonl")


def test_parser_data_only_and_js_numeric_notation():
    assert literal_array("let data=Object.freeze([{n:.5,m:1.,b:!1}])") == [
        {"n": 0.5, "m": 1.0, "b": False}
    ]
    with pytest.raises(ValueError, match="Duplicate"):
        literal_array("const data=[{id:1,id:2}]")
    assert literal_array("const data=[{id:1,id:2}]", allow_duplicate_keys=True) == [{"id": 2}]
    for source in ("const data=[run()]", "const data=[1+run()]", "const data=[{x:process.env}]"):
        with pytest.raises(ValueError):
            literal_array(source)


def test_static_tables_do_not_execute_constructors():
    source = 'n("Season","Weather",["rain","snow"]), dangerous("x", process.env, [])'
    rows = list(table_calls(source))
    assert len(rows) == 1 and rows[0]["dimension"] == "к2"
    details = other_details(rows[0], "table")
    assert details["outcome_count"] == details["die_sides"] == 2
    assert "rain" not in json.dumps(details)


def test_typed_spell_units_and_components():
    details = spell_details(
        {
            "level": 3,
            "school": "Воплощение",
            "application_time": "1 бонусное действие",
            "duration": "10 минут",
            "distance": "120 футов",
            "components": "В, С, М",
            "classes": ["Волшебник"],
            "ritual": "нет",
            "concentration": True,
            "description": "Урон 8к6 огнём.",
        }
    )
    assert details["casting_unit"] == "bonus_action"
    assert details["duration_seconds"] == 600 and details["range_feet"] == 120
    assert details["components"] == ["verbal", "somatic", "material"]
    assert details["source_dice"] == ["8d6"]
    assert details["ritual"] is False and details["concentration"] is True
    assert spell_details({})["range_feet"] == -1


@pytest.mark.parametrize("value", ["нет", "no", "false", "", False, "0"])
def test_negative_source_booleans(value):
    assert source_bool(value) is False
    assert magic_details({"attunement": value})["requires_attunement"] is False


def test_race_inheritance_extraction():
    details = race_details(
        {
            "speed_land": 30,
            "speed_air": "Нет",
            "dark_vision": "60 футов",
            "characteristics": [{"wisdom": 2}],
            "languages": ["Общий"],
        },
        "",
        [],
    )
    assert details["speed_walk_ft"] == 30 and details["speed_fly_ft"] == -1
    assert details["darkvision_ft"] == 60
    assert details["ability_bonuses"] == [{"ability": "wisdom", "bonus": 2}]


def test_primary_data_does_not_mix_condition_registry():
    conditions = [{"name": "Blind", "description": "text"}]
    assert list(catalog_records(conditions, "feats")) == []
    assert normalized_key("Table: Ancient sword") in name_keys("Table: Ancient sword [Old Sword]")


def normalized_key(value):
    from rpg_vkr.world_library.model import normalized

    return normalized(value)


def test_static_section_prose_stays_transient():
    source = "<h2>Wall</h2><p>Protected prose.</p><table><tr><td>КД</td><td>17</td></tr></table>"
    section = next(html_sections(source))
    details = other_details(section)
    assert details["numeric_parameters"] == [{"field": "КД [column 1]", "value": 17}]
    assert "Protected prose" not in json.dumps(details)
    assert not other_details({"html": "<script>let unrelated='99d6'</script>"})["source_dice"]


def test_full_class_and_race_hierarchy(references):
    by_id = {r["id"]: r for r in references}
    classes = [r for r in references if r["attributes"]["record_type"] == "class"]
    assert len(classes) == 9673
    roots = [r for r in classes if not r["attributes"]["details"]["parent_global_id"]]
    assert len(roots) == 55
    assert sum(":base:" in unquote(r["attributes"]["source_url"]) for r in classes) == 753
    assert sum(":subclass:" in unquote(r["attributes"]["source_url"]) for r in classes) == 7550
    assert len(classes) - len(roots) - 753 - 7550 == 1315
    for row in classes:
        d = row["attributes"]["details"]
        for child in d["child_ids"]:
            assert by_id[child]["attributes"]["details"]["parent_global_id"] == row["id"]
        assert len(row["links"]) == len(d["child_ids"]) + bool(d["parent_global_id"])
    races = [r for r in references if r["attributes"]["record_type"] == "race"]
    assert len(races) == 319
    assert sum(bool(r["attributes"]["details"]["parent_global_id"]) for r in races) == 153
    moons = [r for r in classes if r["attributes"]["source_name"] == "Жрец: Домен луны"]
    assert len(moons) == 2
    assert not set(moons[0]["attributes"]["details"]["child_ids"]) & set(
        moons[1]["attributes"]["details"]["child_ids"]
    )


def test_enrichment_report_and_source_fingerprints(references):
    report = json.loads((ROOT / "data/world_library/reference-enrichment.json").read_text("utf-8"))
    counts = Counter(r["attributes"]["data_state"] for r in references)
    assert len(references) == report["reference_records"] == 20251
    assert counts["needs-source-resolution"] == report["unresolved"]
    assert report["enriched"] + report["unresolved"] == len(references)
    assert counts["index-control"] == 129
    assert report["full_mechanical_implementation"] is False
    for row in references:
        a = row["attributes"]
        if a["data_state"] in {"source-structured", "source-section"}:
            assert len(a["source_asset_sha256"]) == 64
            assert a["source_asset"].startswith("https://rpgd100.ru/")
        assert a["mechanics_state"] == (
            "mp-adapted" if a.get("source_spell_v1") else "reference-only"
        )
        if a.get("source_spell_v1"):
            validate_record(row)


def test_invalid_typed_parameters_and_broken_parents(references):
    row = deepcopy(next(r for r in references if r["attributes"]["record_type"] == "spell"))
    row["attributes"]["details"]["level"] = True
    with pytest.raises(ValueError, match="integer"):
        validate_record(row)
    row["attributes"]["details"]["level"] = 1
    row["attributes"]["source_asset_sha256"] = "invalid"
    with pytest.raises(ValueError, match="fingerprint"):
        validate_record(row)
    row = deepcopy(next(r for r in references if r["attributes"]["record_type"] == "class"))
    row["attributes"]["details"]["parent_global_id"] = "absent_id"
    with pytest.raises(ValueError, match="hierarchy"):
        validate_bundle([row])


def test_repeat_index_scan_preserves_verified_details(references):
    old = references[0]
    incoming = deepcopy(old)
    for key in ("record_type", "details", "source_asset", "source_asset_sha256", "data_state"):
        incoming["attributes"].pop(key)
    incoming["description"] = "Index-only description."
    incoming["links"] = []
    assert preserve_details(incoming, {old["id"]: old}) == old
    changed = deepcopy(incoming)
    changed["attributes"]["native_id"] = "different"
    changed["description"] = "Changed identity."
    assert preserve_details(changed, {old["id"]: old})["description"] == "Changed identity."


def test_card_surface_excludes_navigation_and_other_cards():
    parser = CardSurface()
    parser.feed(
        '<nav>Ignore me</nav><div class="catalog-index-entry-surface">'
        "<div><h2>Shield</h2><p>AC&nbsp;2</p></div></div><footer>Also ignore</footer>"
    )
    result = "".join(parser.parts)
    assert "Shield" in result and "AC&nbsp;2" in result
    assert "Ignore" not in result and "Also ignore" not in result


@pytest.mark.parametrize(
    "level,expected", [("Заговор", 0), ("cantrip", 0), ("3 уровень", 3), ("не указан", -1), (0, 0)]
)
def test_cantrip_level_is_recovered_without_inventing_unknown_levels(level, expected):
    assert spell_details({"level": level})["level"] == expected


def test_index_refresh_preserves_executable_source_spell_and_its_adaptation(references):
    old = next(r for r in references if r["attributes"].get("source_spell_v1"))
    incoming = deepcopy(old)
    incoming["attributes"].pop("source_spell_v1")
    incoming["attributes"]["mechanics_state"] = "reference-only"
    restored = preserve_details(incoming, {old["id"]: old})
    assert restored["attributes"]["source_spell_v1"] == old["attributes"]["source_spell_v1"]
    assert restored["attributes"]["mechanics_state"] == "mp-adapted"
    validate_record(restored)
