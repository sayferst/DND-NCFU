"""Reproducible preview sample; no generated records, approvals, or world mutations."""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import all_records, digest  # noqa: E402
from rpg_vkr.world_library.presentation import card  # noqa: E402


def sample(records, seed):
    excluded = {"source_reference", "skill", "race"}
    groups = {}
    for row in records:
        if row["profile"] not in excluded:
            groups.setdefault(row["profile"], []).append(row)
    rng = random.Random(seed)
    selected = []
    for profile in sorted(groups):
        selected.extend(rng.sample(sorted(groups[profile], key=lambda r: r["id"]), 2))
    remaining = [r for r in groups["source_creature"] if r not in selected]
    selected.extend(rng.sample(sorted(remaining, key=lambda r: r["id"]), 50 - len(selected)))
    rng.shuffle(selected)
    by_id = {r["id"]: r for r in records}
    return {
        "seed": seed,
        "method": "two random records per spawnable profile, remaining source creatures",
        "population": sum(map(len, groups.values())),
        "count": len(selected),
        "by_profile": dict(Counter(r["profile"] for r in selected)),
        "cards": [card(r, resolve=by_id.get, revision=1) for r in selected],
        "record_digests": {r["id"]: digest(r) for r in selected},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new sample file")
    result = sample(all_records(), args.seed)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"cards": result["count"], "population": result["population"], "seed": result["seed"]}
        )
    )


if __name__ == "__main__":
    main()
