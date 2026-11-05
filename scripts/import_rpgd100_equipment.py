"""Complete equipment/tools index, with bounded mechanical facts and original summaries."""

import hashlib
import json
import re
from pathlib import Path

from import_rpgd100_facts import fetch, literal_array

ROOT = Path(__file__).resolve().parents[1]
FACT_KEYS = {
    "type",
    "weight",
    "price",
    "damage",
    "damage_type",
    "range",
    "properties",
    "armor_class",
    "strength",
    "stealth",
    "cost",
    "ac",
    "weight_lb",
}


def main():
    inventory = json.loads(
        (ROOT / "data/world_library/rpgd100-all-indexes.json").read_text(encoding="utf-8")
    )
    rows = []
    coverage = []
    for catalog in inventory["catalogs"]:
        if catalog["catalog"] not in {"/content_pages/equipment", "/content_pages/tools"}:
            continue
        html = fetch("https://rpgd100.ru" + catalog["catalog"]).decode("utf-8")
        facts = {}
        for script in re.findall(r'<script[^>]+src="([^"?]+)', html):
            if script.rsplit("/", 1)[-1] not in {
                "armor.js",
                "weapons.js",
                "equipment.js",
                "firearms.js",
                "siege_equipment.js",
                "trade_goods.js",
                "poisons.js",
                "drugs.js",
                "tools.js",
            }:
                continue
            source = fetch("https://rpgd100.ru" + script).decode("utf-8")
            for match in re.finditer(r"(?:const|let|var)\s+\w+\s*=\s*\[", source):
                try:
                    data = literal_array(source[match.start() :])
                except (ValueError, IndexError):
                    continue
                for value in data:
                    if not isinstance(value, dict):
                        continue
                    name = value.get("name_ru", value.get("name", ""))
                    if isinstance(name, str):
                        facts[name.casefold()] = value
        matched = 0
        for entry in catalog["entries"]:
            source_id, title, english, path, section = entry[:5]
            name = re.sub(r"\s*\[.*\]$", "", title).strip()
            data = facts.get(name.casefold(), {})
            selected = []
            for key in sorted(FACT_KEYS & data.keys()):
                value = data[key]
                if isinstance(value, (int, float, bool)):
                    value = str(value)
                if isinstance(value, list) and all(isinstance(x, str) for x in value):
                    value = ", ".join(value)
                if isinstance(value, str) and len(value) <= 180:
                    selected.append({"field": key, "value": " ".join(value.split())})
            matched += bool(selected)
            identifier = (
                "rpg_equipment_"
                + hashlib.sha256((catalog["catalog"] + ":" + source_id).encode()).hexdigest()[:24]
            )
            rows.append(
                {
                    "id": identifier,
                    "name": name[:65] + " · " + identifier[-8:],
                    "profile": "source_equipment",
                    "category": "reference.source_equipment",
                    "description": (
                        f"{name[:100]} — запись раздела «{section}». Назначение и "
                        f"допустимое применение определяются типом снаряжения; наличие "
                        f"в справочнике не означает выдачу предмета персонажу. Это "
                        f"оригинальное краткое описание, а не текст источника."
                    ),
                    "price_cp": 0,
                    "attributes": {
                        "source_url": "https://rpgd100.ru" + path,
                        "source_name": name[:160],
                        "section": section[:100],
                        "facts": selected,
                        "missing_numeric_facts": not bool(selected),
                        "price_status": "unparsed-source-price; price_cp is not a market valuation",
                    },
                    "links": [],
                    "provenance": {
                        "origin": "source-facts/original-description",
                        "source": "https://rpgd100.ru" + path[:370],
                        "generator": "rpg-equipment-1",
                        "review": "unreviewed",
                    },
                }
            )
        coverage.append(
            {
                "catalog": catalog["catalog"],
                "indexed": len(catalog["entries"]),
                "with_facts": matched,
            }
        )
    from rpg_vkr.world_library.model import dump, read_jsonl, validate_bundle

    validate_bundle(rows)
    out = ROOT / "data/world_library/rpgd100-equipment-facts.jsonl"
    out.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    assert len(read_jsonl(out)) == len(rows)
    (out.parent / "rpgd100-equipment-report.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"records": len(rows), "coverage": coverage}))


if __name__ == "__main__":
    main()
