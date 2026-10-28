"""Public-action class campaign; normal hero kit, finite town, real enemy templates."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from test_adventure import world_value  # noqa: E402

from rpg_vkr.application import Session  # noqa: E402
from rpg_vkr.domain import game_catalog as c  # noqa: E402
from rpg_vkr.domain.adventure import build_world  # noqa: E402
from rpg_vkr.domain.catalog import Definition, Entity  # noqa: E402
from rpg_vkr.domain.character import ABILITY_NAMES, Character  # noqa: E402
from rpg_vkr.domain.unified import CLASSES, level  # noqa: E402
from rpg_vkr.unified_session import UnifiedSession  # noqa: E402


def genesis(class_id, seed):
    s = UnifiedSession.create(
        Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True))),
        class_id,
        CLASSES[class_id][4],
        seed=seed,
        catalog_revision=3,
    )
    w = world_value()
    w["title"] = "Поселение у лесной дороги"
    w["private_plot"] = "Оригинальный проверочный маршрут без скрытых подарков."
    w["places"].append(
        {
            "id": "mine",
            "name": "Старый рудник",
            "parent": "pier",
            "description": "Короткая дорога к забою.",
        }
    )
    w["entities"] = [e for e in w["entities"] if e["id"] not in ("watcher", "stock", "rope")]
    w["definitions"] = [d for d in w["definitions"] if d["id"] == "seller_type"]
    w["definitions"][0]["properties"]["can_trade"] = True
    for job in ("farmer", "smith"):
        w["definitions"].append(
            {
                "id": job + "_type",
                "name": {"farmer": "Огородница Мира", "smith": "Кузнец Орин"}[job],
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {"class": job, "hp_max": 18, "can_trade": True},
            }
        )
        w["entities"].append(
            {
                "id": job,
                "definition_id": job + "_type",
                "parent_id": "pier",
                "state": {"hp": 18, "gold_cp": 100},
            }
        )
    for station in ("forge", "alchemy", "workbench"):
        w["definitions"].append(
            {
                "id": station + "_type",
                "name": "Общее рабочее место " + station,
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"station": station, "public": True},
            }
        )
        w["entities"].append(
            {"id": "station_" + station, "definition_id": station + "_type", "parent_id": "pier"}
        )
    w["definitions"].append(
        {
            "id": "worker_tools",
            "name": "Инструменты мастерской",
            "kind": "item",
            "categories": ["miscellaneous"],
            "properties": {"game_template_id": "house_0_0", "durability": 20},
        }
    )
    w["entities"].append(
        {
            "id": "smith_tools",
            "definition_id": "worker_tools",
            "parent_id": "smith",
            "owner_id": "smith",
        }
    )
    s.start_world(build_world(w, s, "authored-normal-kit-class-campaign"))
    return s


def rehearse(class_id, seed, max_enemies):
    begin = time.perf_counter()
    s = genesis(class_id, seed)
    counts = {}
    milestones = []
    errors = []

    def act(command, **args):
        result = s.perform_gameplay(command, args, s._request_token())
        counts[command] = counts.get(command, 0) + 1
        if not milestones or level(s.gameplay["xp"]) != milestones[-1]["level"]:
            milestones.append(
                {"level": level(s.gameplay["xp"]), "turn": len(s.turns), "xp": s.gameplay["xp"]}
            )
            print(class_id, milestones[-1], flush=True)
        return result

    def qty(key):
        return sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i["owner"] == "hero" and i.get("template") == key
        )

    def wait_shop(merchant):
        for _ in range(32):
            a = next(a for a in s.catalog.entities if a.id == merchant)
            if (
                s.actor_is_here(merchant)
                and (a.state or {}).get("closed_until", 0) <= s.gameplay["minute"]
            ):
                return
            act("wait", minutes=180)
        raise ValueError("merchant absent after four days")

    def obtain(key, n):
        for _ in range(30):
            if qty(key) >= n:
                return
            goods = [
                i
                for i in s.gameplay["items"]
                if i["owner"] in ("seller", "smith") and i.get("template") == key
            ]
            bought = False
            for item in goods:
                try:
                    wait_shop(item["owner"])
                    act("buy", merchant=item["owner"], item=item["id"])
                    bought = True
                    break
                except ValueError:
                    pass
            if bought:
                continue
            row = c.row(key)
            if row["kind"] == "material" and not row["process"]:
                for destination in ("pier", "path", "mine"):
                    if s.interaction_state().current != destination:
                        if s.interaction_state().current != "pier":
                            safe_travel("pier")
                        if destination != "pier":
                            safe_travel(destination)
                    if s.gameplay["living_world"]["nodes"][destination].get(key, 0) > 0:
                        act(
                            "gather",
                            material=key,
                            quantity=min(
                                5,
                                n - qty(key),
                                s.gameplay["living_world"]["nodes"][destination][key],
                            ),
                        )
                        break
                else:
                    act("wait", minutes=1440)
            elif key == "house_0_0":
                act("wait", minutes=1440)
            else:
                raise ValueError("unsupported resource acquisition " + key)
        if qty(key) < n:
            raise ValueError("resource exhausted " + key)

    def learn(key):
        for _ in range(24):
            if key in s.gameplay["known_recipes"] or key in s.gameplay["spells"]:
                return
            obtain("mat_2_0", 1)
            obtain("mat_3_0", 1)
            act("research", entry=key)
        raise ValueError("learning exhausted " + key)

    def safe_travel(dest):
        for _ in range(8):
            try:
                act("travel", destination=dest)
                return
            except ValueError as error:
                if "перекрыт" not in str(error):
                    raise
                act("wait", minutes=1440)
        raise ValueError("road remained closed")

    def maintenance():
        if s.gameplay["battle"]:
            raise ValueError("maintenance called during battle")
        for _ in range(8):
            status = [
                x
                for x in s.gameplay["statuses"].get("hero", [])
                if x["op"] in ("burn", "bleed", "poison")
            ]
            if not status:
                break
            minutes = max(x["until"] for x in status) - s.gameplay["minute"] + 1
            act("wait", minutes=min(1440, max(1, minutes)))
        act("rest")
        if class_id in ("mage", "cleric"):
            for key in ("heal", "bolt"):
                if key not in s.gameplay["spells"]:
                    learn(key)
        if s.interaction_state().current != "pier":
            safe_travel("pier")
        # Sale of actual spoils pays for tools/materials; no grants or XP assignment.
        for item in list(s.gameplay["items"]):
            if item["owner"] != "hero" or not item.get("template", "").startswith("mat_"):
                continue
            keep = (
                8
                if item["template"].startswith(("mat_0_", "mat_1_", "mat_2_", "mat_3_", "mat_4_"))
                else 0
            )
            for _ in range(max(0, item["quantity"] - keep)):
                try:
                    wait_shop("seller")
                    act("sell", merchant="seller", item=item["id"])
                except ValueError:
                    break
        if not any(
            i["owner"] == "hero" and i.get("template") == "house_0_0" and i["durability"] > 0
            for i in s.gameplay["items"]
        ):
            obtain("house_0_0", 1)
        for item in list(s.gameplay["items"]):
            if item["owner"] != "hero" or item["durability"] >= min(item["durability_cap"], 18):
                continue
            row = c.row(item.get("template", "house_0_0"))
            if row["kind"] not in ("weapon", "armour", "household"):
                continue
            base = c.row(row["material"])["base"]
            recipe = next(
                r
                for r in c.available("recipe", level(s.gameplay["xp"]), category="repair")
                if r["compatible_material"] == base
            )
            learn(recipe["id"])
            for _ in range(24):
                if item["durability"] >= min(item["durability_cap"], 18):
                    break
                for key, n in recipe["ingredients"].items():
                    obtain(key, n)
                act("repair", recipe=recipe["id"], item=item["id"])
                item = next(i for i in s.gameplay["items"] if i["id"] == item["id"])
        if class_id == "archer":
            while qty("use_ammunition_0_0") < 36:
                obtain("mat_0_0", 2)
                obtain("mat_1_0", 1)
                act("manufacture", recipe="recipe_production_0_0", result="use_ammunition_0_0")
        lv = level(s.gameplay["xp"])
        while 2 * sum(lv >= x for x in (4, 8, 12, 16, 20)) > sum(
            s.gameplay["ability_increases"].values()
        ):
            primary = (
                "intelligence"
                if class_id == "mage"
                else "wisdom"
                if class_id == "cleric"
                else "dexterity"
                if class_id in ("archer", "rogue")
                else "strength"
            )
            act(
                "raise",
                ability=primary if getattr(s.effective_character, primary) < 20 else "constitution",
            )
        if len(s.gameplay["talents"]) < 1 + sum(lv >= x for x in (5, 10, 15, 20)):
            choices = [
                r
                for r in c.available("talent", lv, category=class_id)
                if r["effects"][0]["op"] == "damage" and r["id"] not in s.gameplay["talents"]
            ]
            if choices:
                act("talent", talent=choices[-1]["id"])

    victories = 0
    with c.using(3):
        targets = sorted(c.available("creature"), key=lambda r: (r["level"], r["hp"], r["id"]))
        try:
            for row in targets[:max_enemies]:
                if level(s.gameplay["xp"]) == 20:
                    break
                maintenance()
                if s.interaction_state().current != "pier":
                    safe_travel("pier")
                key = "gc_" + row["id"]
                id = "trial_" + row["id"]
                d = Definition(
                    key,
                    row["name"][:100],
                    "actor",
                    ("creatures",),
                    {
                        "game_template_id": row["id"],
                        "hp_max": row["hp"],
                        "armour_class": row["defence"],
                        "strength": row["strength"],
                        "dexterity": row["dexterity"],
                        "damage_dice": row["dice"],
                        "weapon": row["weapon"],
                        "behavior": row["behavior"],
                        "resistance": row["resistance"],
                        "vulnerability": row["vulnerability"],
                        "peaceful": row["peaceful"],
                    },
                    origin="generated",
                )
                a = Entity(
                    id,
                    key,
                    "pier",
                    state={
                        "hp": row["hp"],
                        "st": 20,
                        "mp": 10,
                        "encounter_source": "authored-class-route",
                    },
                )
                s.register_catalog(
                    "На дороге появляется противник",
                    [d],
                    [a],
                    "Авторский проверочный маршрут",
                    "authored-integration-campaign",
                )
                counts["world_registration"] = counts.get("world_registration", 0) + 1
                act("encounter", enemies=[id])
                for _ in range(180):
                    if not s.gameplay["battle"]:
                        break
                    if s.world.hp <= 0:
                        raise ValueError("hero defeated")
                    if class_id in ("mage", "cleric") and s.gameplay["mp"] >= 3:
                        spell = "heal" if s.world.hp < s.world.max_hp // 3 else "bolt"
                        act("cast", spell=spell, target="hero" if spell == "heal" else id)
                        continue
                    choices = [c.row(k) for k in s.gameplay["talents"] if k.startswith("talent_")]
                    available = [
                        r
                        for r in choices
                        if r["effects"][0]["op"] == "damage"
                        and s.gameplay["cooldowns"].get(r["id"], 0) <= s.gameplay["minute"]
                        and s.gameplay["st"] >= r["cost_st"]
                        and s.gameplay["mp"] >= r.get("mp", 0)
                    ]
                    if available:
                        act("ability", talent=available[-1]["id"], target=id)
                    elif s.gameplay["st"] < 3:
                        act("recover")
                    else:
                        act("attack", target=id, lethal=False)
                else:
                    raise ValueError("battle round limit")
                if s.world.hp <= 0:
                    raise ValueError("hero defeated")
                if any(
                    a.id == id and (a.state or {}).get("hp", 1) <= 0 for a in s.catalog.entities
                ):
                    victories += 1
        except (ValueError, StopIteration) as error:
            errors.append(str(error) or "no eligible repair recipe")
    payload = json.loads(json.dumps(s.to_dict()))
    restored = Session.from_dict(payload, version=31)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == s.dice.checkpoint()
    return {
        "class": class_id,
        "seed": seed,
        "level": level(s.gameplay["xp"]),
        "turns": len(s.turns),
        "days": s.gameplay["minute"] // 1440,
        "victories": victories,
        "actions": counts,
        "milestones": milestones,
        "errors": errors,
        "replay_and_rng_equal": True,
        "reached_twenty": level(s.gameplay["xp"]) == 20,
        "seconds": time.perf_counter() - begin,
        "conditions": (
            "Normal hero kit and200cp; merchant1000cp plus two workers100cp each. "
            "No injected XP or post-genesis stock. Enemies added by real catalog registrations "
            "using unmodified creature templates. Automated authored scenario, not human play."
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--class-id", choices=CLASSES, required=True)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--max-enemies", type=int, default=320)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise SystemExit("Use a new report filename")
    result = rehearse(a.class_id, a.seed, a.max_enemies)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result["reached_twenty"] else 2)
