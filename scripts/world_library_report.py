"""Rebuild counts from validated files and actual compiler output, never estimated totals."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.creature_rules import compile_creature  # noqa: E402
from rpg_vkr.world_library.equipment_rules import pending_features  # noqa: E402
from rpg_vkr.world_library.model import all_records, dump  # noqa: E402


def main():
    rows = all_records()
    profiles = Counter(row["profile"] for row in rows)
    creatures = [r for r in rows if r["profile"] == "source_creature"]
    unsupported = [
        {
            "id": row["id"],
            "source_url": row["attributes"]["source_url"],
            "features": compile_creature(row)["unsupported_source_features"],
        }
        for row in creatures
    ]
    report = {
        "records": len(rows),
        "by_profile": dict(profiles),
        "creatures": len(creatures),
        "source_attack_formula": sum(
            bool(r["attributes"].get("actions_v2", {}).get("actions"))
            if r["attributes"].get("attack_math_version") == 2
            else bool(r["attributes"]["attacks"])
            for r in creatures
        ),
        "resistances": sum(bool(r["attributes"]["resistances"]) for r in creatures),
        "immunities": sum(bool(r["attributes"]["immunities"]) for r in creatures),
        "vulnerabilities": sum(bool(r["attributes"]["vulnerabilities"]) for r in creatures),
        "simple_multiattack": sum(bool(r["attributes"]["extra_attacks"]) for r in creatures),
        "unconditional_regeneration": sum(bool(r["attributes"]["regeneration"]) for r in creatures),
        "creatures_with_unsupported_features": sum(bool(r["features"]) for r in unsupported),
        "unsupported_feature_occurrences": sum(len(r["features"]) for r in unsupported),
        "homebrew_magic_templates_with_handlers": sum(
            r["profile"] in {"spell", "rune", "scroll", "combination"} for r in rows
        ),
        "homebrew_recipes_with_handlers": profiles["recipe"],
        "undead_fortitude": sum(
            r["attributes"].get("resilience_v1", {}).get("undead_fortitude", False)
            for r in creatures
        ),
        "source_regeneration_programs": sum(
            "regeneration_v1" in r["attributes"] for r in creatures
        ),
        "source_regeneration_with_suppression": sum(
            bool(r["attributes"].get("regeneration_v1", {}).get("suppress_elements"))
            for r in creatures
        ),
        "source_regeneration_with_zero_hp_death_timing": sum(
            r["attributes"].get("regeneration_v1", {}).get("zero_death", False) for r in creatures
        ),
        "homebrew_actors_with_full_stat_blocks": sum(
            r["profile"] in {"npc", "creature", "boss"} and "abilities" in r["attributes"]
            for r in rows
        ),
        "homebrew_npcs_with_social_programs": sum(
            r["profile"] == "npc" and r["provenance"]["generator"] == "world-library-4"
            for r in rows
        ),
        "homebrew_utilities_with_handlers": sum(
            r["profile"] in {"food", "medicine", "poison", "book", "quest"}
            and r["provenance"]["generator"] == "world-library-3"
            for r in rows
        ),
        "reference_records_without_gameplay_handler": profiles["source_reference"],
        "source_equipment_with_pending_special_rules": sum(
            bool(pending_features(row)) for row in rows if row["profile"] == "source_equipment"
        ),
        "source_equipment_with_original_visual_designs": sum(
            row["profile"] == "source_equipment"
            and row["attributes"].get("design_origin") == "invented/homebrew"
            for row in rows
        ),
        "full_rule_coverage": False,
    }
    directory = ROOT / "data/world_library"
    (directory / "runtime-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "unsupported-creature-features.jsonl").write_text(
        "\n".join(dump(row) for row in unsupported if row["features"]) + "\n", encoding="utf-8"
    )
    print(dump(report))


if __name__ == "__main__":
    main()
