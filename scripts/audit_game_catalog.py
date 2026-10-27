"""Counts are derived from released data and a matching real execution proof."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rpg_vkr.domain import game_catalog as catalog


def audit(proof=None):
    data = {"schema": "game-catalog-1", "records": list(catalog.load().values())}
    result = catalog.validate(data)
    tested = set()
    if proof:
        raw = json.loads(Path(proof).read_text(encoding="utf-8"))
        if raw["catalog_sha256"] != catalog.digest():
            raise ValueError("Proof describes another catalog")
        tested = set(raw["tested_ids"])
        if not tested <= catalog.load().keys():
            raise ValueError("Proof contains unknown IDs")
    counts = Counter()
    for id in tested:
        r = catalog.row(id)
        counts[r["kind"] + "/" + r["category"]] += 1
        if r["kind"] == "spell":
            counts["school/" + r["school"]] += 1
    return {
        "catalog_sha256": catalog.digest(),
        "distinct_records": result["total"],
        "distinct_tested_records": len(tested),
        "groups": [
            {
                "category": k,
                "required": 80,
                "registered": n,
                "executed": counts[k],
                "status": "execution_passed" if counts[k] >= 80 else "unverified",
            }
            for k, n in result["categories"].items()
        ],
        "quality_limit": (
            "Controlled execution proves dispatch/state transitions, "
            "not literary originality or all balance interactions"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--proof", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit(args.proof)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("| Категория | Требуется | Зарегистрировано | Исполнено в тесте | Статус |")
    print("|---|---:|---:|---:|---|")
    for r in result["groups"]:
        print(f"|{r['category']}|{r['required']}|{r['registered']}|{r['executed']}|{r['status']}|")
