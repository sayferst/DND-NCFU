"""Version three saves, finite powers, conditions and six-second combat timing."""

import re

from rpg_vkr.domain.character import ability_modifier
from rpg_vkr.world_library.source_geometry import contains, distance, positions

VERSION = "library-creature-3"
ABILITIES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
CONDITIONS = (
    "blinded",
    "charmed",
    "deafened",
    "frightened",
    "grappled",
    "incapacitated",
    "invisible",
    "paralyzed",
    "petrified",
    "poisoned",
    "prone",
    "restrained",
    "stunned",
    "unconscious",
)


def enabled(engine):
    return bool(engine.state.get("source_rules_v3"))


def rules(engine, actor):
    if actor == "hero":
        return {}
    definition = engine.actor(actor, False)[1]
    if definition.properties.get("library_rules_version") != VERSION:
        return {}
    return definition.properties["source_features_v3"]


def initialize(engine):
    if not any(
        d.properties.get("library_rules_version") == VERSION for d in engine.definitions.values()
    ):
        return
    engine.state.setdefault(
        "source_rules_v3",
        {
            "version": 1,
            "step": 0,
            "conditions": {},
            "spent": {},
            "positions": {},
        },
    )
    positions(engine)


def now(engine):
    return engine.state["minute"] * 10 + engine.state["source_rules_v3"]["step"]


def conditions(engine, actor):
    if not enabled(engine):
        return []
    rows = engine.state["source_rules_v3"]["conditions"].get(actor, [])
    return [row for row in rows if row["until"] > now(engine)]


def has(engine, actor, *names):
    return any(row["kind"] in names for row in conditions(engine, actor))


def incapacitated(engine, actor):
    if engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import life

        state = life(engine, actor)
        if state.dead or state.unconscious:
            return True
    return has(engine, actor, "incapacitated", "paralyzed", "petrified", "stunned", "unconscious")


def apply_condition(
    engine, actor, kind, source, rounds, repeat="none", ability="", dc=0, magical=False
):
    if kind not in CONDITIONS or not 1 <= rounds <= 14400:
        raise ValueError("Condition outside source bounds")
    if kind in rules(engine, actor).get("condition_immunities", []):
        engine.events.append({"kind": "source_condition_immune", "actor": actor, "condition": kind})
        return
    data = engine.state["source_rules_v3"]["conditions"].setdefault(actor, [])
    data[:] = [r for r in data if (r["kind"], r["source"]) != (kind, source)]
    data.append(
        {
            "kind": kind,
            "source": source,
            "until": now(engine) + rounds,
            "repeat": repeat,
            "ability": ability,
            "dc": dc,
            "magical": magical,
        }
    )
    engine.events.append(
        {
            "kind": "source_condition",
            "actor": actor,
            "condition": kind,
            "source": source,
            "rounds": rounds,
        }
    )


def attack_mode(engine, actor, target, ranged, extra_advantage=False, extra_disadvantage=False):
    advantage = (
        extra_advantage
        or has(engine, actor, "invisible")
        or has(
            engine,
            target,
            "blinded",
            "paralyzed",
            "petrified",
            "restrained",
            "stunned",
            "unconscious",
        )
    )
    disadvantage = extra_disadvantage or has(
        engine, actor, "blinded", "poisoned", "prone", "restrained"
    )
    disadvantage |= has(engine, target, "invisible")
    if engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import life

        advantage |= life(engine, target).unconscious
    if has(engine, target, "prone"):
        advantage |= not ranged and distance(engine, actor, target) <= 5
        disadvantage |= ranged or distance(engine, actor, target) > 5
    battle = engine.state.get("battle")
    if rules(engine, actor).get("pack_tactics") and battle:
        advantage |= any(
            ally not in {actor, target}
            and battle["sides"].get(ally) == battle["sides"].get(actor)
            and engine.hp(ally) > 0
            and not incapacitated(engine, ally)
            and distance(engine, ally, target) <= 5
            for ally in battle["order"]
        )
    for row in conditions(engine, actor):
        if row["kind"] == "frightened" and row["source"] in positions(engine):
            disadvantage |= (
                positions(engine)[actor]["place"] == positions(engine)[row["source"]]["place"]
            )
    return int(bool(advantage)) - int(bool(disadvantage))


def cannot_attack(engine, actor, target):
    return incapacitated(engine, actor) or any(
        row["kind"] == "charmed" and row["source"] == target for row in conditions(engine, actor)
    )


def speed(engine, actor, base):
    if incapacitated(engine, actor) or has(engine, actor, "grappled", "restrained"):
        return 0
    return base // 2 if has(engine, actor, "prone") else base


def roll_d20(engine, mode, reason):
    first = engine.roll("1d20", reason)
    if mode:
        second = engine.roll("1d20", reason + (" — преимущество" if mode > 0 else " — помеха"))
        return max(first, second) if mode > 0 else min(first, second)
    return first


def saving_throw(engine, actor, ability, dc, *, magical=False):
    if ability not in ABILITIES or type(dc) is not int or not 1 <= dc <= 40:
        raise ValueError("Invalid source saving throw")
    spec = rules(engine, actor)
    automatic = ability in {"strength", "dexterity"} and has(
        engine, actor, "paralyzed", "petrified", "stunned", "unconscious"
    )
    mode = int(bool(magical and spec.get("magic_resistance")))
    mode -= int(ability == "dexterity" and has(engine, actor, "restrained"))
    mode = (mode > 0) - (mode < 0)
    natural = None if automatic else roll_d20(engine, mode, "Спасбросок " + ability)
    if actor == "hero":
        bonus = ability_modifier(getattr(engine.char, ability))
    else:
        properties = engine.actor(actor, False)[1].properties
        bonus = spec.get("save_bonuses", {}).get(
            ability, ability_modifier(properties.get(ability, 10))
        )
    if automatic:
        success, total = False, None
    elif engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules import check
        from rpg_vkr.domain.owner_rules_runtime import life

        offset = max(0, dc - 30)
        result = check(
            natural,
            bonus - offset,
            min(dc, 30),
            exhaustion=life(engine, actor).exhaustion,
            partial=False,
        )
        success, total = result["succeeded"], result["total"] + offset
        if result["complication"]:
            engine.owner_complication_minutes = getattr(engine, "owner_complication_minutes", 0) + 1
    else:
        total = natural + bonus
        success = total >= dc
    budget = engine.state["source_rules_v3"]["spent"].setdefault(actor, {})
    maximum = spec.get("legendary_resistance", 0)
    used = budget.get("legendary", 0)
    legendary = not success and used < maximum
    if legendary:
        budget["legendary"] = used + 1
        success = True
    engine.events.append(
        {
            "kind": "source_save",
            "actor": actor,
            "ability": ability,
            "natural": natural,
            "bonus": bonus,
            "total": total,
            "dc": dc,
            "magical": magical,
            "legendary": legendary,
            "success": success,
        }
    )
    return success


def effect_rolls(engine, components):
    values = []
    for part in components:
        formula = re.fullmatch(r"(\d+d\d+)([+-]\d+)?", part["dice"])
        values.append(
            (
                max(0, engine.roll(formula[1], "Урон способности") + int(formula[2] or 0)),
                part["element"],
            )
        )
    return values


def save_effect(engine, source, target, effect, rolled=None):
    if (
        effect["condition"] in rules(engine, target).get("condition_immunities", [])
        and not effect["components"]
    ):
        engine.events.append(
            {"kind": "source_condition_immune", "actor": target, "condition": effect["condition"]}
        )
        return [], None
    success = saving_throw(
        engine, target, effect["ability"], effect["dc"], magical=effect["magical"]
    )
    rolled = rolled if rolled is not None else effect_rolls(engine, effect["components"])
    packet = [
        (amount // 2 if success and effect["half"] else 0 if success else amount, element)
        for amount, element in rolled
    ]
    condition = (
        None
        if success or not effect["condition"]
        else {
            "actor": target,
            "kind": effect["condition"],
            "source": source,
            "rounds": effect["rounds"],
            "repeat": effect["repeat"],
            "ability": effect["ability"],
            "dc": effect["dc"],
            "magical": effect["magical"],
        }
    )
    return packet, condition


def before_actor(engine, actor):
    if not enabled(engine):
        return True
    spec = rules(engine, actor)
    budget = engine.state["source_rules_v3"]["spent"].setdefault(actor, {})
    budget["reaction"] = 0
    budget["legendary_action"] = 0
    for index, power in enumerate(spec.get("powers", [])):
        key = "recharge:" + str(index)
        if power["recharge"] and budget.get(key):
            value = engine.roll("1d6", "Перезарядка: " + power["name"])
            if value >= power["recharge"]:
                budget[key] = 0
            engine.events.append(
                {
                    "kind": "source_recharge",
                    "actor": actor,
                    "power": index,
                    "roll": value,
                    "ready": not budget[key],
                }
            )
    repeat_saves(engine, actor, "start")
    return not incapacitated(engine, actor)


def repeat_saves(engine, actor, phase):
    rows = engine.state["source_rules_v3"]["conditions"].get(actor, [])
    for row in list(conditions(engine, actor)):
        if row["repeat"] == phase and saving_throw(
            engine, actor, row["ability"], row["dc"], magical=row.get("magical", False)
        ):
            rows.remove(row)


def after_actor(engine, actor):
    if enabled(engine):
        repeat_saves(engine, actor, "end")
        legendary_actions(engine, actor)


def legendary_actions(engine, ended):
    battle = engine.state["battle"]
    if not battle:
        return
    from rpg_vkr.domain.catalog_actions_v2 import hit

    for actor in list(battle["order"]):
        if (
            actor == ended
            or actor == "hero"
            or engine.hp(actor) <= 0
            or incapacitated(engine, actor)
        ):
            continue
        spec = rules(engine, actor)
        budget = engine.state["source_rules_v3"]["spent"].setdefault(actor, {})
        used = budget.get("legendary_action", 0)
        for action in spec.get("legendary", []):
            if used + action["cost"] > spec["legendary_max"]:
                continue
            bounds = selected(engine.actor(actor, False)[1].properties, action["index"])
            targets = [
                id
                for id in battle["order"]
                if battle["sides"][id] != battle["sides"][actor]
                and engine.hp(id) > 0
                and not cannot_attack(engine, actor, id)
                and distance(engine, actor, id) <= bounds["maximum_range"]
            ]
            if not targets:
                continue
            target = min(targets, key=engine.hp)
            budget["legendary_action"] = used + action["cost"]
            hit(engine, actor, target, source_attack=action["index"])
            engine.events.append(
                {
                    "kind": "source_legendary_action",
                    "actor": actor,
                    "name": action["name"],
                    "cost": action["cost"],
                    "after": ended,
                }
            )
            break


def parry(engine, defender, attacker, natural, total, defence, ranged):
    if defender == "hero" or ranged or natural in {1, 20} or incapacitated(engine, defender):
        return defence
    bonus = rules(engine, defender).get("parry", 0)
    if not bonus or has(engine, defender, "blinded") or has(engine, attacker, "invisible"):
        return defence
    if engine.status_power(defender, "disarm"):
        return defence
    budget = engine.state["source_rules_v3"]["spent"].setdefault(defender, {})
    if not budget.get("reaction") and defence <= total < defence + bonus:
        budget["reaction"] = 1
        engine.events.append({"kind": "source_parry", "actor": defender, "bonus": bonus})
        return defence + bonus
    return defence


def turn_order(engine, followers):
    for actor in followers:
        if enabled(engine) and engine.hp(actor) > 0 and not before_actor(engine, actor):
            engine.events.append({"kind": "source_incapacitated", "actor": actor})
            after_actor(engine, actor)
            continue
        try:
            yield actor
        finally:
            after_actor(engine, actor)


def tick(engine, command, was_battle):
    if not enabled(engine) or not was_battle or command in {"rest", "wait", "advance"}:
        return
    state = engine.state["source_rules_v3"]
    state["step"] += 1
    minutes, state["step"] = divmod(state["step"], 10)
    engine.action_minutes = minutes


def long_rest(engine):
    if not enabled(engine):
        return
    party = {"hero"} | {
        id
        for id, side in (engine.state.get("last_battle") or {}).get("sides", {}).items()
        if side == "party"
    }
    spent = engine.state["source_rules_v3"]["spent"]
    for actor in party:
        if actor == "hero" or (
            actor in engine.refs
            and engine.refs[actor].place == engine.scene.current
            and engine.hp(actor) > 0
        ):
            spent.pop(actor, None)


def selected(properties, index):
    source = properties["source_features_v3"]
    from copy import deepcopy

    from rpg_vkr.world_library.creature_actions import selected as old_selected

    rider = next((r for r in source["riders"] if r["index"] == index), None)
    if rider:
        action = deepcopy(properties["source_actions_v2"]["actions"][index])
        action.update(
            components=rider["base"],
            dice=rider["base"][0]["dice"],
            element=rider["base"][0]["element"],
            complete=True,
        )
    else:
        action = dict(old_selected(properties, index))
    bounds = next((r for r in source["ranges"] if r["index"] == index), None)
    if bounds:
        action.update(normal_range=bounds["normal"], maximum_range=bounds["maximum"])
    else:
        action.update(
            normal_range=60 if action["ranged"] else 5,
            maximum_range=120 if action["ranged"] else 5,
            range_homebrew=True,
        )
    return action


def hero_range(engine, item, row, target):
    """Source facts when present; explicit conservative homebrew for legacy weapons."""
    from rpg_vkr.world_library.source_geometry import distance

    ranged = row.get("category") in {"longbow", "crossbow"}
    normal, maximum, origin = (60, 120, "homebrew") if ranged else (5, 5, "homebrew")
    entity = engine.actors.get((item or {}).get("source"))
    if entity:
        attrs = engine.definitions[entity.definition_id].properties.get("library_attributes", {})
        facts = attrs.get("facts", [])
        properties = " ".join(
            r["value"] for r in facts if r.get("field") in {"properties", "range"}
        ).casefold()
        match = re.search(
            r"(?:дис(?:т(?:анция)?)?\.?|дальность)\s*\(?\s*(\d+)\s*/\s*(\d+)", properties
        )
        if ranged and match and 1 <= int(match[1]) <= int(match[2]) <= 2000:
            normal, maximum, origin = int(match[1]), int(match[2]), "source"
        elif not ranged and ("досягаемость" in properties or "длинное" in properties):
            normal, maximum, origin = 10, 10, "source"
    separation = distance(engine, "hero", target)
    if separation > maximum:
        raise ValueError("Target exceeds weapon range; move before attacking")
    engine.events.append(
        {
            "kind": "source_weapon_range",
            "actor": "hero",
            "normal": normal,
            "maximum": maximum,
            "origin": origin,
        }
    )
    return separation > normal


def attack_rider(engine, source, target, index, packet):
    rider = next((r for r in rules(engine, source).get("riders", []) if r["index"] == index), None)
    if rider is None:
        return packet, None
    extra, condition = save_effect(engine, source, target, rider["effect"])
    return packet + extra, condition


def turn(engine, actor, target, properties):
    from rpg_vkr.domain.catalog_actions_v2 import hit
    from rpg_vkr.world_library.damage_packets import apply as damage_packet

    spec = properties["source_features_v3"]
    if cannot_attack(engine, actor, target):
        engine.events.append({"kind": "source_cannot_attack", "actor": actor, "target": target})
        return
    budget = engine.state["source_rules_v3"]["spent"].setdefault(actor, {})
    for index, power in enumerate(spec["powers"]):
        if power["recharge"] and budget.get("recharge:" + str(index)):
            continue
        if power["daily"] and budget.get("daily:" + str(index), 0) >= power["daily"]:
            continue
        points = positions(engine)
        if distance(engine, actor, target) > power["range"]:
            continue
        if power["shape"] == "one":
            targets = [target]
        else:
            targets = [
                id
                for id in ["hero", *sorted(engine.refs)]
                if engine.hp(id) > 0
                and points[id]["place"] == points[actor]["place"]
                and contains(
                    power["shape"],
                    points[actor]["point"],
                    points[target]["point"],
                    points[id]["point"],
                    power["size"],
                    power["width"],
                )
            ]
        if not targets:
            continue
        if power["recharge"]:
            budget["recharge:" + str(index)] = 1
        if power["daily"]:
            budget["daily:" + str(index)] = budget.get("daily:" + str(index), 0) + 1
        rolled = effect_rolls(engine, power["effect"]["components"])
        for victim in targets:
            packet, condition = save_effect(engine, actor, victim, power["effect"], rolled)
            if packet:
                damage_packet(engine, victim, packet, actor)
            if condition and engine.hp(victim) > 0:
                apply_condition(engine, **condition)
        engine.events.append(
            {
                "kind": "source_power",
                "actor": actor,
                "index": index,
                "name": power["name"],
                "targets": targets,
            }
        )
        return
    actions = properties["source_actions_v2"]["actions"]
    available = [
        i
        for i, a in enumerate(actions)
        if a["complete"] or any(r["index"] == i for r in spec["riders"])
    ]
    if not available:
        from rpg_vkr.world_library.creature_actions import turn as old_turn

        old_turn(engine, actor, target, properties)
        return
    sequence = spec["multiattack"] or [available[0]]
    movement = speed(engine, actor, max(spec["speed"], spec["fly_speed"]))
    if engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import life

        movement = max(0, movement - 5 * life(engine, actor).exhaustion)
    for index in sequence:
        if engine.hp(actor) <= 0 or engine.hp(target) <= 0:
            break
        action = selected(properties, index)
        if distance(engine, actor, target) > action["maximum_range"]:
            from rpg_vkr.world_library.source_geometry import approach

            movement -= approach(engine, actor, target, action["normal_range"], movement)
        if distance(engine, actor, target) > action["maximum_range"]:
            break
        hit(engine, actor, target, source_attack=index)
