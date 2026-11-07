"""Paired authored resource scenarios. No claim about human narrative quality."""

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from rpg_vkr.domain.strategic_conflicts import FoodState, food_options


def run():
    started = time.perf_counter()
    rows = []
    for food in (40, 60, 80, 100, 120):
        for treasury in (0, 20, 40, 80):
            for supplier in (False, True):
                state = FoodState(food=food, treasury=treasury, supplier_available=supplier)
                options = food_options(state)
                # Baseline is one fixed preference. Formal condition reports alternatives
                # and each agent's preferred option; never chooses for a real player.
                for option, outcome in options.items():
                    after = outcome["after"]
                    conserved = (
                        after["food"] + after["supplier_food"] + sum(outcome["allocation"].values())
                        == state.food + state.supplier_food
                        and after["treasury"] + after["supplier_money"]
                        == state.treasury + state.supplier_money
                    )
                    rows.append(
                        {
                            "scenario": asdict(state),
                            "option": option,
                            "baseline": option == "civilians",
                            "conserved": conserved,
                            "pareto": outcome["pareto"],
                            "utilities": outcome["utilities"],
                            "unmet": outcome["unmet"],
                        }
                    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return {
        "schema": "conflict-trials-v1",
        "scope": "authored_finite_resource_simulation",
        "code_commit": revision,
        "code_sha256": hashlib.sha256(
            Path("src/rpg_vkr/domain/strategic_conflicts.py").read_bytes()
        ).hexdigest(),
        "scenarios": 40,
        "outcomes": len(rows),
        "constraint_violations": sum(not r["conserved"] for r in rows),
        "elapsed_seconds": time.perf_counter() - started,
        "rows": rows,
        "narrative_quality": "NOT_MEASURED",
        "human_evaluation": "NOT_PERFORMED",
        "research_claim": "Resource conservation and distinct authored preferences only",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ("scenarios", "outcomes", "constraint_violations")}))


if __name__ == "__main__":
    main()
