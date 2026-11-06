"""Attach checked numeric action sequences without copying source action prose."""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from import_rpgd100_facts import fetch, literal_bindings  # noqa: E402

from rpg_vkr.world_library.creature_actions import extract, validate  # noqa: E402
from rpg_vkr.world_library.model import dump, read_jsonl, validate_bundle  # noqa: E402


def main():
    directory = ROOT / "data/world_library"
    path = directory / "rpgd100-creature-facts.jsonl"
    rows = read_jsonl(path)
    by_id = {r["id"]: r for r in rows}
    report = json.loads((directory / "rpgd100-import-report.json").read_text("utf-8"))
    matched = set()
    for source in report["sources"]:
        raw = fetch(source["url"])
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Source changed; reinventory before extracting mechanics")
        text = raw.decode("utf-8")
        for values in literal_bindings(text):
            if not isinstance(values, list):
                continue
            for entry in values:
                if not isinstance(entry, dict) or "статблок" not in entry:
                    continue
                slug = entry.get("slug", entry.get("id", entry.get("название", "")))
                id = (
                    "rpg_"
                    + hashlib.sha256((source["url"] + "#" + str(slug)).encode()).hexdigest()[:24]
                )
                if id not in by_id:
                    continue
                rules = extract(entry["статблок"])
                from rpg_vkr.world_library.grapple_rules import extract as extract_grapple

                program = extract_grapple(entry["статблок"], rules["actions"])
                by_id[id]["attributes"].pop("grapple_v1", None)
                if program:
                    by_id[id]["attributes"]["grapple_v1"] = program
                validate(rules)
                by_id[id]["attributes"]["actions_v2"] = rules
                by_id[id]["attributes"]["attack_math_version"] = 2
                matched.add(id)
    if len(matched) != len(rows):
        raise ValueError(f"Source reconciliation incomplete: {len(matched)}/{len(rows)}")
    validate_bundle(rows)
    path.write_text("\n".join(dump(row) for row in rows) + "\n", encoding="utf-8")
    counts = Counter()
    for row in rows:
        rules = row["attributes"]["actions_v2"]
        complete = [a for a in rules["actions"] if a["complete"]]
        counts["source_creatures"] += 1
        counts["typed_attacks"] += len(rules["actions"])
        counts["complete_attacks"] += len(complete)
        counts["complete_single_damage_attacks"] += sum(
            len(a.get("components", [])) <= 1 for a in complete
        )
        counts["mixed_damage_attacks"] += sum(len(a.get("components", [])) > 1 for a in complete)
        counts["creatures_with_complete_attack_choices"] += bool(complete)
        counts["creatures_with_multiple_complete_attack_choices"] += len(complete) > 1
        counts["exact_multiattack_sequences"] += rules["multiattack_complete"]
        counts["mixed_multiattack_sequences"] += len(set(rules["multiattack"])) > 1
    result = dict(counts) | {"version": "library-creature-2", "complete_rule_coverage": False}
    (directory / "creature-actions-coverage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(dump(result))


if __name__ == "__main__":
    main()
