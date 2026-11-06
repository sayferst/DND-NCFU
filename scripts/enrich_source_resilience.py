"""Reconcile additional source programs with the existing pinned source assets."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from import_rpgd100_facts import fetch, literal_bindings  # noqa: E402

from rpg_vkr.world_library.model import dump, read_jsonl, validate_bundle  # noqa: E402
from rpg_vkr.world_library.resilience_rules import extract  # noqa: E402


def main():
    directory = ROOT / "data/world_library"
    path = directory / "rpgd100-creature-facts.jsonl"
    rows = read_jsonl(path)
    by_id = {r["id"]: r for r in rows}
    for row in rows:
        row["attributes"].pop("resilience_v1", None)
    sources = json.loads((directory / "rpgd100-import-report.json").read_text("utf-8"))
    matched = set()
    for source in sources["sources"]:
        raw = fetch(source["url"])
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Source changed; reconcile its version first")
        content = raw.decode("utf-8")
        for entries in literal_bindings(content):
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or "статблок" not in entry:
                    continue
                slug = entry.get("slug", entry.get("id", entry.get("название", "")))
                id = (
                    "rpg_"
                    + hashlib.sha256((source["url"] + "#" + str(slug)).encode()).hexdigest()[:24]
                )
                if id not in by_id:
                    continue
                program = extract(entry["статблок"])
                if program["supported_names"]:
                    by_id[id]["attributes"]["resilience_v1"] = program
                matched.add(id)
    if matched != set(by_id):
        raise ValueError("Incomplete source reconciliation")
    validate_bundle(rows)
    path.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    report = {
        "version": "library-resilience-1",
        "reconciled_creatures": len(matched),
        "undead_fortitude": sum("resilience_v1" in r["attributes"] for r in rows),
        "full_rule_coverage": False,
    }
    (directory / "source-resilience-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(dump(report))


if __name__ == "__main__":
    main()
