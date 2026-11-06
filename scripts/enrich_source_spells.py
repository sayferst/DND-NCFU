"""Pinned source spell facts to audited MP programs; no source prose is published."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from enrich_rpgd100_references import clean, spell_details  # noqa: E402
from import_rpgd100_facts import fetch, literal_bindings  # noqa: E402

from rpg_vkr.world_library.model import dump, validate_bundle  # noqa: E402
from rpg_vkr.world_library.source_magic_rules import VERSION, mp_cost  # noqa: E402

ASSET = "https://rpgd100.ru/scripts/spells.js?v=1793709915"
ASSET_SHA = "327711db91a48464679e74031d41f471fae5061561372d6cd290b3bd5ed793e4"
AUDITED = {
    "d27917107c3cb27cd2ebed25ee208052eec19c2c7f011cd3ec4ea84e62a1d598": ("constitution_save", 10),
    "ae50b9bc60f6cc01cb84d6f5c2f726bbb225aa938625e11179abe174545469e8": ("ranged_attack", 30),
}


def main():
    raw = fetch(ASSET)
    if hashlib.sha256(raw).hexdigest() != ASSET_SHA:
        raise ValueError("Pinned spell source changed")
    sources = []
    for values in literal_bindings(raw.decode("utf-8")):
        if isinstance(values, list):
            sources.extend(
                r
                for r in values
                if isinstance(r, dict) and {"name_ru", "level", "school"} <= r.keys()
            )
    path = ROOT / "data/world_library/rpgd100-reference-index.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    corrected = handled = 0
    matched = set()
    for row in rows:
        a = row["attributes"]
        if a.get("record_type") != "spell" or a.get("source_asset") != ASSET:
            continue
        old = a["details"]
        choices = []
        for source in sources:
            name = clean(source["name_ru"]).casefold()
            if not a["source_name"].casefold().startswith(name + " ["):
                continue
            detail = spell_details(source)
            if all(old[k] == v for k, v in detail.items() if k != "level"):
                choices.append((source, detail))
        if len(choices) != 1:
            continue
        source, detail = choices[0]
        if old["level"] == -1 and detail["level"] == 0:
            a["details"] = detail
            corrected += 1
        sha = hashlib.sha256(clean(source.get("description"), 100000).encode()).hexdigest()
        if sha not in AUDITED:
            continue
        mode, distance = AUDITED[sha]
        if detail["level"] != 0 or detail["range_feet"] != distance or detail["concentration"]:
            raise ValueError("Audited spell metadata mismatch")
        a["mechanics_state"] = "mp-adapted"
        a["source_spell_v1"] = {
            "version": VERSION,
            "level": 0,
            "mp": mp_cost(0),
            "mode": mode,
            "range_ft": distance,
            "dice": "1d12",
            "element": "poison",
            "source_prose_sha256": sha,
            "adaptation": "MP; reviewed formula grants use; scene geometry",
        }
        handled += 1
        matched.add(sha)
    if matched != set(AUDITED):
        raise ValueError("Audited source spell reconciliation incomplete")
    validate_bundle(rows)
    path.write_text("\n".join(dump(r) for r in rows) + "\n", encoding="utf-8")
    result = {
        "version": VERSION,
        "source_spell_programs": handled,
        "cantrip_levels_corrected": corrected,
        "full_rule_coverage": False,
        "source_prose_published": False,
    }
    (ROOT / "data/world_library/source-spells-coverage.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(dump(result))


if __name__ == "__main__":
    main()
