"""Reconcile pinned creature sources with version-three source-rule programs."""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from import_rpgd100_facts import fetch, literal_array  # noqa: E402

from rpg_vkr.world_library.model import dump, validate_bundle  # noqa: E402
from rpg_vkr.world_library.source_extract import extract  # noqa: E402


def main():
    directory = ROOT / "data/world_library"
    path = directory / "rpgd100-creature-facts.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    for row in rows:
        row["attributes"].pop("features_v3", None)
    validate_bundle(rows)
    by_id = {row["id"]: row for row in rows}
    report = json.loads((directory / "rpgd100-import-report.json").read_text("utf-8"))
    matched = set()
    for source in report["sources"]:
        raw = fetch(source["url"])
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Source hash changed; reinventory required")
        source_text = raw.decode("utf-8")
        for match in re.finditer(r"(?:const|let|var)\s+\w+\s*=\s*\[", source_text):
            try:
                entries = literal_array(source_text[match.start() :], allow_duplicate_keys=True)
            except (ValueError, IndexError):
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
                row = by_id[id]
                row["attributes"]["features_v3"] = extract(
                    entry["статблок"], row["attributes"]["actions_v2"]
                )
                matched.add(id)
    if matched != set(by_id):
        raise ValueError("Source reconciliation is incomplete")
    validate_bundle(rows)
    path.write_text("\n".join(dump(row) for row in rows) + "\n", encoding="utf-8")
    count = Counter()
    for row in rows:
        program = row["attributes"]["features_v3"]
        count["creatures"] += 1
        count["magic_resistance"] += program["magic_resistance"]
        count["pack_tactics"] += program["pack_tactics"]
        count["legendary_resistance"] += bool(program["legendary_resistance"])
        count["riders"] += len(program["riders"])
        count["save_powers"] += len(program["powers"])
        count["recharge_powers"] += sum(bool(p["recharge"]) for p in program["powers"])
        count["daily_powers"] += sum(bool(p["daily"]) for p in program["powers"])
        count["multiattacks"] += bool(program["multiattack"])
        count["source_feature_occurrences"] += len(program["supported_names"])
        count["legendary_actions"] += len(program["legendary"])
        count["parry"] += bool(program["parry"])
    result = dict(count) | {"version": "library-creature-3", "full_rule_coverage": False}
    (directory / "source-rules-coverage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(dump(result))


if __name__ == "__main__":
    main()
