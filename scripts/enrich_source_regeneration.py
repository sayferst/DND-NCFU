"""Parse complete pinned regeneration clauses; raw prose stays in the private cache."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from import_rpgd100_facts import fetch, literal_bindings  # noqa: E402

from rpg_vkr.world_library.model import dump, read_jsonl, validate_bundle  # noqa: E402
from rpg_vkr.world_library.regeneration_rules import extract  # noqa: E402


def main():
    directory = ROOT / "data/world_library"
    path = directory / "rpgd100-creature-facts.jsonl"
    rows = read_jsonl(path)
    by_id = {r["id"]: r for r in rows}
    matched = set()
    sources = json.loads((directory / "rpgd100-import-report.json").read_text("utf-8"))["sources"]
    for source in sources:
        raw = fetch(source["url"])
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Pinned source changed")
        for entries in literal_bindings(raw.decode("utf-8")):
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("статблок"), dict):
                    continue
                slug = entry.get("slug", entry.get("id", entry.get("название", "")))
                id = (
                    "rpg_"
                    + hashlib.sha256((source["url"] + "#" + str(slug)).encode()).hexdigest()[:24]
                )
                if id not in by_id:
                    continue
                attributes = by_id[id]["attributes"]
                attributes.pop("regeneration_v1", None)
                program = extract(entry["статблок"])
                if program:
                    attributes["regeneration_v1"] = program
                matched.add(id)
    if matched != set(by_id):
        raise ValueError("Creature reconciliation incomplete")
    validate_bundle(rows)
    path.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    programs = [
        r["attributes"]["regeneration_v1"] for r in rows if "regeneration_v1" in r["attributes"]
    ]
    result = {
        "version": "library-regeneration-1",
        "reconciled_creatures": len(rows),
        "programs": len(programs),
        "suppression": sum(bool(p["suppress_elements"]) for p in programs),
        "zero_death_timing": sum(p["zero_death"] for p in programs),
        "full_rule_coverage": False,
    }
    (directory / "source-regeneration-coverage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(dump(result))


if __name__ == "__main__":
    main()
