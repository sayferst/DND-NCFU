"""Public-action progression rehearsal. Authored rich warehouse, not class combat balance."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from test_catalog_campaign import act, started  # noqa: E402

from rpg_vkr.application import Session  # noqa: E402
from rpg_vkr.domain import game_catalog as content  # noqa: E402
from rpg_vkr.domain.unified import CLASSES, level  # noqa: E402


def rehearse(class_id):
    s = started(class_id, supplies=True, catalog_revision=2)
    begin = time.perf_counter()
    milestones = [{"level": 1, "turn": 0, "xp": 0}]
    skipped = []

    def quantity(id):
        return sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i.get("template") == id and i["owner"] == "hero"
        )

    def learn(recipe):
        if recipe["level"] > level(s.gameplay["xp"]):
            raise ValueError("recipe level")
        for _ in range(24):
            if recipe["id"] in s.gameplay["known_recipes"]:
                return
            act(s, "research", entry=recipe["id"])
        raise ValueError("research attempts exhausted")

    def ensure_tools():
        # Processing intermediate materials also wears tools. Replenish before
        # every such operation, while a usable kit still remains.
        def durability():
            return sum(
                i["durability"]
                for i in s.gameplay["items"]
                if i["owner"] == "hero" and content.row(i["template"]).get("capability") == "tools"
            )

        recipe = content.row("recipe_production_0_0")
        while durability() < 5:
            if not durability():
                raise ValueError("controller exhausted all tools")
            learn(recipe)
            required = recipe["materials_by_output"]["house_0_0"]
            if any(quantity(id) < n for id, n in required.items()):
                raise ValueError("finite raw tool supply exhausted")
            act(s, "manufacture", recipe=recipe["id"], result="house_0_0")

    def materials(ingredients, depth=0):
        if depth > 10:
            raise ValueError("unexpected material cycle")
        for id, required in ingredients.items():
            while quantity(id) < required:
                recipe = next((r for r in content.available("recipe") if id in r["outputs"]), None)
                if recipe is None:
                    raise ValueError("finite raw supply exhausted")
                learn(recipe)
                materials(recipe["materials_by_output"][id], depth + 1)
                ensure_tools()
                act(s, "manufacture", recipe=recipe["id"], result=id)

    with content.using(2):
        products = (
            content.available("weapon")
            + content.available("armour")
            + content.available("household")
        )
        products.sort(key=lambda r: (r["level"], r["id"]))
        for product in products:
            lv = level(s.gameplay["xp"])
            if lv == 20:
                break
            if product["level"] > lv:
                continue
            try:
                recipe = next(
                    r for r in content.available("recipe") if product["id"] in r["outputs"]
                )
                learn(recipe)
                for _ in range(40):
                    materials(recipe["materials_by_output"][product["id"]])
                    ensure_tools()
                    act(s, "manufacture", recipe=recipe["id"], result=product["id"])
                    made = next(
                        (
                            i
                            for i in s.gameplay["items"]
                            if i.get("template") == product["id"]
                            and i["owner"] == "hero"
                            and i.get("made_by") == "hero"
                        ),
                        None,
                    )
                    if made:
                        break
                else:
                    raise ValueError("craft attempts exhausted")
                for _ in range(48):
                    merchant = next(e for e in s.catalog.entities if e.id == "seller")
                    remaining = (merchant.state or {}).get("closed_until", 0) - s.gameplay["minute"]
                    if remaining > 0 or not s.actor_is_here("seller"):
                        act(s, "wait", minutes=min(1440, max(60, remaining)))
                        continue
                    act(s, "sell", merchant="seller", item=made["id"])
                    break
                else:
                    raise ValueError("merchant unavailable")
            except ValueError as error:
                skipped.append({"product": product["id"], "reason": str(error)})
                continue
            lv = level(s.gameplay["xp"])
            if lv > milestones[-1]["level"]:
                milestones.append({"level": lv, "turn": len(s.turns), "xp": s.gameplay["xp"]})
                print(class_id, milestones[-1], flush=True)
            while 2 * sum(lv >= n for n in (4, 8, 12, 16, 20)) > sum(
                s.gameplay["ability_increases"].values()
            ):
                ability = (
                    "intelligence" if s.effective_character.intelligence < 20 else "constitution"
                )
                act(s, "raise", ability=ability)
    value = json.loads(json.dumps(s.to_dict(), ensure_ascii=False))
    r = Session.from_dict(value, version=31)
    assert r.to_dict() == s.to_dict() and r.dice.checkpoint() == s.dice.checkpoint()
    return {
        "class": class_id,
        "level": level(s.gameplay["xp"]),
        "turns": len(s.turns),
        "days": s.gameplay["minute"] // 1440,
        "milestones": milestones,
        "skipped": skipped,
        "seconds": time.perf_counter() - begin,
        "save_bytes": len(json.dumps(value, ensure_ascii=False).encode("utf-8")),
        "replay_and_rng_equal": True,
        "reached_level_twenty": level(s.gameplay["xp"]) == 20,
        "catalog_sha256": s.gameplay["catalog_hash"],
        "conditions": (
            "Authored finite 400-units-per-raw-material warehouse and merchant200000cp; "
            "all post-genesis changes through Session; no injected XP/level."
        ),
        "limitations": (
            "Class-neutral manufacturing/trade progression, not class-specific combat balance, "
            "a scarce market or human play."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classes", nargs="+", choices=CLASSES, default=list(CLASSES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for class_id in args.classes:
        report = rehearse(class_id)
        (args.output / (class_id + ".json")).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps({k: report[k] for k in ("class", "level", "turns", "seconds")}), flush=True
        )
