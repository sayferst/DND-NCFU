"""Complete equipment/tools index, with bounded mechanical facts and original summaries."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from import_rpgd100_facts import fetch, literal_bindings

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
        fact_sources = {}
        resources = [("https://rpgd100.ru" + catalog["catalog"], html)]
        for script in re.findall(r'<script[^>]+src="([^"?]+)', html):
            address = urljoin("https://rpgd100.ru" + catalog["catalog"], script)
            parsed = urlsplit(address)
            if parsed.scheme != "https" or parsed.hostname != "rpgd100.ru":
                continue
            if not parsed.path.endswith(".js"):
                continue
            resources.append((address, fetch(address).decode("utf-8")))
        for address, source in resources:
            source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            for data in literal_bindings(source):
                for value in data if isinstance(data, list) else [data]:
                    if not isinstance(value, dict):
                        continue
                    name = value.get("name_ru", value.get("name", ""))
                    if isinstance(name, str):
                        old = facts.get(name.casefold(), {})
                        if len(FACT_KEYS & value.keys()) > len(FACT_KEYS & old.keys()):
                            facts[name.casefold()] = value
                            fact_sources[name.casefold()] = {
                                "source_asset": address,
                                "source_asset_sha256": source_hash,
                            }
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
                        **fact_sources.get(name.casefold(), {}),
                    },
                    "links": [],
                    "provenance": {
                        "origin": "source-facts/original-description",
                        "source": "https://rpgd100.ru" + path[:370],
                        "generator": "rpg-equipment-2",
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
    from rpg_vkr.world_library.equipment_designs import enrich as enrich_design
    from rpg_vkr.world_library.equipment_packs import enrich as enrich_package
    from rpg_vkr.world_library.equipment_rules import compile_equipment
    from rpg_vkr.world_library.model import dump, read_jsonl, validate_bundle

    for row in rows:
        rules = compile_equipment(row)
        enrich_package(row, rules)
        rules = compile_equipment(row)
        row["price_cp"] = rules["price_cp"]
        row["attributes"]["price_status"] = (
            "homebrew-estimate" if "price_cp" in rules["homebrew_fields"] else "source-price-parsed"
        )
        enrich_design(row)

    validate_bundle(read_jsonl(ROOT / "data/world_library/seed-v1.jsonl") + rows)
    out = ROOT / "data/world_library/rpgd100-equipment-facts.jsonl"
    out.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    assert len(read_jsonl(out, dependencies=read_jsonl(out.parent / "seed-v1.jsonl"))) == len(rows)
    (out.parent / "rpgd100-equipment-report.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"records": len(rows), "coverage": coverage}))


if __name__ == "__main__":
    main()
