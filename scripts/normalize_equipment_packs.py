"""Normalize finite package quantities without replacing source IDs or source facts."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.equipment_packs import enrich  # noqa: E402
from rpg_vkr.world_library.equipment_rules import compile_equipment  # noqa: E402
from rpg_vkr.world_library.model import dump, read_jsonl, validate_bundle  # noqa: E402


def main():
    path = ROOT / "data/world_library/rpgd100-equipment-facts.jsonl"
    seed = read_jsonl(path.parent / "seed-v1.jsonl")
    rows = read_jsonl(path, dependencies=seed)
    count = 0
    for row in rows:
        row["attributes"].pop("pack_v1", None)
        enrich(row, compile_equipment(row))
        if "pack_v1" not in row["attributes"]:
            continue
        row["price_cp"] = compile_equipment(row)["price_cp"]
        row["attributes"]["price_status"] = (
            "homebrew-package; rounded-display-unit-price"
            if row["attributes"]["pack_v1"].get("price_is_homebrew")
            else "source-package; rounded-display-unit-price"
        )
        row["provenance"]["generator"] = "rpg-equipment-pack-1"
        count += 1
    validate_bundle(seed + rows)
    path.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(rows), "normalized_packages": count}))


if __name__ == "__main__":
    main()
