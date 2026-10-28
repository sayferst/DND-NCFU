"""Work-only progression on finite supplies and funded demand; no warehouse or combat XP."""

import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from rehearse_class_campaign import ROOT, genesis

from rpg_vkr.domain import game_catalog as c
from rpg_vkr.domain.unified import level
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots


def rehearse(goal, destination):
    s = genesis("artisan", 17)
    counts, errors, milestones = Counter(), [], []
    begin = time.perf_counter()

    def act(command, **args):
        if len(s.turns) >= 5000:
            raise ValueError("Controller action limit")
        s.perform_gameplay(command, args, s._request_token())
        counts[command] += 1
        if not milestones or level(s.gameplay["xp"]) != milestones[-1]["level"]:
            milestones.append(
                {"level": level(s.gameplay["xp"]), "turn": len(s.turns), "xp": s.gameplay["xp"]}
            )
            print(milestones[-1], flush=True)

    def quantity(key):
        return sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i["owner"] == "hero" and i.get("template") == key
        )

    def travel(place):
        if place == s.interaction_state().current:
            return
        if s.interaction_state().current != "pier" and place != "pier":
            travel("pier")
        for _ in range(10):
            try:
                act("travel", destination=place)
                return
            except ValueError as error:
                if "перекрыт" not in str(error):
                    raise
                act("wait", minutes=1440)
        raise ValueError("Road remained closed")

    def raw(key, required):
        for _ in range(80):
            if quantity(key) >= required:
                return
            # Buy an actual unit when possible; this replenishes the buyer's purse.
            if s.actor_is_here("seller"):
                item = next(
                    (
                        i
                        for i in s.gameplay["items"]
                        if i["owner"] == "seller" and i.get("template") == key
                    ),
                    None,
                )
                if item:
                    try:
                        act("buy", merchant="seller", item=item["id"])
                        continue
                    except ValueError:
                        pass
            for place in ("pier", "path", "mine", "forest"):
                w = s.gameplay["living_world"]
                stock = w["nodes"][place].get(key, 0)
                stock += w["society"]["places"][place]["deposits"].get(key, 0)
                if stock:
                    travel(place)
                    act("gather", material=key, quantity=min(5, stock, required - quantity(key)))
                    break
            else:
                raise ValueError("Finite raw resource exhausted: " + key)
        raise ValueError("Gather attempts exhausted: " + key)

    def learn(recipe):
        for _ in range(24):
            if recipe["id"] in s.gameplay["known_recipes"]:
                return
            raw("mat_2_0", 1)
            raw("mat_3_0", 1)
            act("research", entry=recipe["id"])
        raise ValueError("Research attempt limit")

    def tools():
        remaining = max(
            (
                i["durability"]
                for i in s.gameplay["items"]
                if i["owner"] == "hero" and c.row(i["template"]).get("capability") == "tools"
            ),
            default=0,
        )
        if remaining >= 6:
            return
        if remaining < 1:
            raise ValueError("All real tools exhausted")
        recipe = c.row("recipe_production_0_0")
        learn(recipe)
        for key, n in recipe["materials_by_output"]["house_0_0"].items():
            raw(key, n)
        travel("pier")
        act("manufacture", recipe=recipe["id"], result="house_0_0")

    def materials(required, depth=0):
        if depth > 8:
            raise ValueError("Material dependency cycle")
        for key, n in required.items():
            while quantity(key) < n:
                row = c.row(key)
                if row["kind"] == "material" and not row["process"]:
                    raw(key, n)
                    continue
                recipe = next(
                    r for r in c.available("recipe", level(s.gameplay["xp"])) if key in r["outputs"]
                )
                learn(recipe)
                tools()
                materials(recipe["materials_by_output"][key], depth + 1)
                travel("pier")
                act("manufacture", recipe=recipe["id"], result=key)

    with c.using(3):
        products = c.available("weapon") + c.available("armour") + c.available("household")
        products.sort(key=lambda r: (r["level"], r["price_cp"], r["id"]))
        try:
            for product in products:
                if level(s.gameplay["xp"]) >= goal:
                    break
                if product["level"] > level(s.gameplay["xp"]):
                    continue
                recipe = next(
                    r
                    for r in c.available("recipe", level(s.gameplay["xp"]))
                    if product["id"] in r["outputs"]
                )
                learn(recipe)
                made = None
                for _ in range(24):
                    tools()
                    materials(recipe["materials_by_output"][product["id"]])
                    tools()
                    materials(recipe["materials_by_output"][product["id"]])
                    travel("pier")
                    act("manufacture", recipe=recipe["id"], result=product["id"])
                    made = next(
                        (
                            i
                            for i in s.gameplay["items"]
                            if i["owner"] == "hero"
                            and i.get("made_by") == "hero"
                            and i.get("template") == product["id"]
                        ),
                        None,
                    )
                    if made:
                        break
                if not made:
                    raise ValueError("Craft attempt limit")
                sold = False
                for _ in range(32):
                    try:
                        act("sell", merchant="seller", item=made["id"])
                        sold = True
                        break
                    except ValueError as error:
                        purchased = False
                        if "недостаточно средств" in str(error):
                            goods = sorted(
                                (i for i in s.gameplay["items"] if i["owner"] == "seller"),
                                key=lambda i: (
                                    c.row(i["template"])["kind"] != "material",
                                    i["price_cp"],
                                ),
                            )
                            for good in goods:
                                try:
                                    act(
                                        "buy",
                                        merchant="seller",
                                        item=good["id"],
                                        quantity=min(5, good["quantity"]),
                                    )
                                    purchased = True
                                    break
                                except ValueError:
                                    continue
                        if not purchased:
                            act("wait", minutes=180)
                if not sold:
                    raise ValueError("Funded demand exhausted")
        except (ValueError, StopIteration) as error:
            errors.append(str(error) or "No accessible recipe")
    slots = SaveSlots(destination / "saves")
    slots.save(1, s)
    r = slots.load(1)
    repo = CampaignRepository(destination / "campaigns.sqlite3")
    repo.sync(s)
    assert r.to_dict() == s.to_dict() == repo.load(repo.identity(s)).to_dict()
    assert r.dice.checkpoint() == s.dice.checkpoint()
    path = destination / "saves/slot-1.json"
    return {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "class": "artisan",
        "goal": goal,
        "level": level(s.gameplay["xp"]),
        "turns": len(s.turns),
        "days": s.gameplay["minute"] // 1440,
        "milestones": milestones,
        "actions": dict(counts),
        "errors": errors,
        "seconds": time.perf_counter() - begin,
        "seed": 17,
        "json_sqlite_replay_rng_equal": True,
        "json_bytes": path.stat().st_size,
        "json_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "conditions": (
            "Normal artisan kit and200cp; merchant1000cp, two workers100cp each. "
            "Finite deposits and forest, no stock or XP edits after genesis. "
            "Only research, gathering, crafting and funded sales; no combat. "
            "Buyer liquidity is recycled through real purchases of existing goods. "
            "Authored automated controller, not human play."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal-level", type=int, choices=range(2, 21), default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--save-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.save_directory.exists():
        raise SystemExit("Use new result paths")
    result = rehearse(args.goal_level, args.save_directory)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result["level"] >= args.goal_level else 2)
