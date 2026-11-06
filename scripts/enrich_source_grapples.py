"""Pinned source grapple clauses and explicit Athletics/Acrobatics bonuses."""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from import_rpgd100_facts import fetch, literal_bindings  # noqa: E402

from rpg_vkr.world_library.creature_actions import extract as extract_actions  # noqa: E402
from rpg_vkr.world_library.creature_actions import text  # noqa: E402
from rpg_vkr.world_library.grapple_rules import extract  # noqa: E402
from rpg_vkr.world_library.model import dump, validate_bundle  # noqa: E402


def main():
    directory = ROOT / "data/world_library"
    path = directory / "rpgd100-creature-facts.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    by_id = {r["id"]: r for r in rows}
    sources = json.loads((directory / "rpgd100-import-report.json").read_text("utf-8"))["sources"]
    matched = set()
    programs = attacks = 0
    for source in sources:
        raw = fetch(source["url"])
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Pinned grapple source changed")
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
                a = by_id[id]["attributes"]
                a.pop("grapple_v1", None)
                stat = entry["статблок"]
                choices = extract_actions(stat)
                program = extract(stat, choices["actions"])
                a["actions_v2"] = choices
                if program:
                    a["grapple_v1"] = program
                    programs += 1
                    attacks += len(program["attacks"])
                skills = stat.get("навыки", {})
                bonuses = {}
                for words, skill in [
                    (("атлетика", "athletics"), "athletics"),
                    (("акробатика", "acrobatics"), "acrobatics"),
                ]:
                    if isinstance(skills, dict):
                        value = next(
                            (v for k, v in skills.items() if text(k).casefold() in words), None
                        )
                        m = re.fullmatch(r"[+-]?\s*\d+", str(value).strip())
                    else:
                        m = re.search(
                            r"(?:" + "|".join(words) + r")\s*([+-]\s*\d+)", text(skills).casefold()
                        )
                        value = m[1] if m else None
                    if m:
                        number = int(str(value).replace(" ", ""))
                        if -10 <= number <= 50:
                            bonuses[skill] = number
                if bonuses:
                    a["skill_bonuses_v1"] = bonuses
                else:
                    a.pop("skill_bonuses_v1", None)
                from rpg_vkr.world_library.multiattack_rules import extract as extract_multiattack
                from rpg_vkr.world_library.source_extract import extract as extract_features

                a["features_v3"] = extract_features(stat, choices)
                a.pop("multiattack_v1", None)
                multiattack = extract_multiattack(stat, choices, a["features_v3"])
                if multiattack:
                    a["multiattack_v1"] = multiattack
                matched.add(id)
    if matched != set(by_id):
        raise ValueError("Grapple reconciliation incomplete")
    validate_bundle(rows)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    temporary.replace(path)
    result = {
        "version": "library-grapple-1",
        "programs": programs,
        "attack_programs": attacks,
        "reconciled": len(rows),
        "full_rule_coverage": False,
    }
    (directory / "source-grapples-coverage.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(dump(result))


if __name__ == "__main__":
    main()
