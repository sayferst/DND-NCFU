"""Import every published catalog entry and reconcile existing enriched records by source."""

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import dump, normalized, read_jsonl, validate_bundle  # noqa: E402


def canonical(url):
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    path = parts.path.replace(".php", "")
    slug = unquote(parts.fragment or query.get("monster", query.get("item", [""]))[0])
    return path, slug


def main():
    out = ROOT / "data/world_library"
    index = json.loads((out / "rpgd100-all-indexes.json").read_text(encoding="utf-8"))
    if not index["complete_indexes"]:
        raise ValueError("Catalog inventory incomplete")
    existing = read_jsonl(out / "seed-v1.jsonl")
    existing += read_jsonl(out / "rpgd100-creature-facts.jsonl")
    existing += read_jsonl(out / "rpgd100-equipment-facts.jsonl")
    by_url = {}
    by_name = {}
    for row in existing:
        attributes = row["attributes"]
        if "source_url" not in attributes:
            continue
        path, slug = canonical(attributes["source_url"])
        if slug:
            by_url[(path, slug)] = row["id"]
        by_name[(path, normalized(attributes["source_name"]))] = row["id"]
    rows = {}
    mappings = []
    coverage = []
    for catalog in index["catalogs"]:
        linked = 0
        for entry in catalog["entries"]:
            native, title, english, url, section = entry[:5]
            title = " ".join(title.split())
            name = re.sub(r"\s*\[.*\]$", "", title).strip()
            key = canonical(url)
            id = by_url.get(key) or by_name.get((catalog["catalog"], normalized(name)))
            if id:
                linked += 1
            else:
                id = (
                    "rpg_index_"
                    + hashlib.sha256((catalog["catalog"] + ":" + native).encode()).hexdigest()[:24]
                )
                source_url = url if url.startswith("https://") else "https://rpgd100.ru" + url
                kind = catalog["catalog"].rsplit("/", 1)[-1]
                rows[id] = {
                    "id": id,
                    "name": name[:65] + " · " + id[-8:],
                    "profile": "source_reference",
                    "category": "reference." + kind + ".source_reference",
                    "price_cp": 0,
                    "description": (
                        f"{name[:120]} — справочная запись раздела «{kind}». Исходный "
                        f"идентификатор и ссылка сохранены для проверки. Числовые "
                        f"параметры и игровые эффекты этой записи требуют отдельной "
                        f"структурированной модели; название не даёт персонажу "
                        f"возможностей автоматически."
                    ),
                    "attributes": {
                        "source_url": source_url,
                        "source_name": title[:250],
                        "source_catalog": catalog["catalog"],
                        "native_id": native,
                        "english_name": english[:200],
                        "section": section[:150],
                        "mechanics_state": "reference-only",
                    },
                    "links": [],
                    "provenance": {
                        "origin": "source-facts/original-description",
                        "source": source_url[:400],
                        "generator": "rpg-all-index-1",
                        "review": "unreviewed",
                    },
                }
            mappings.append(
                {"catalog": catalog["catalog"], "source_id": native, "canonical_id": id}
            )
        coverage.append(
            {
                "catalog": catalog["catalog"],
                "source_entries": len(catalog["entries"]),
                "reconciled_enriched": linked,
                "reference_entries": len(catalog["entries"]) - linked,
            }
        )
    all_rows = existing + list(rows.values())
    validate_bundle(all_rows)
    (out / "rpgd100-reference-index.jsonl").write_text(
        "\n".join(dump(r) for r in rows.values()) + "\n", encoding="utf-8"
    )
    (out / "rpgd100-source-ids.jsonl").write_text(
        "\n".join(dump(r) for r in mappings) + "\n", encoding="utf-8"
    )
    report = {
        "source_entries": len(mappings),
        "canonical_records": len(all_rows),
        "new_reference_records": len(rows),
        "catalogs": coverage,
        "complete_catalog_entry_coverage": True,
        "complete_mechanical_implementation": False,
        "note": (
            "Full index coverage is not full rule implementation, full "
            "prose import or human review."
        ),
    }
    (out / "rpgd100-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(dump({k: v for k, v in report.items() if k != "catalogs"}))


if __name__ == "__main__":
    main()
