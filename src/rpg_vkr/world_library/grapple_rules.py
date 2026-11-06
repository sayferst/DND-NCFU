"""Finite on-hit grapples: persistent links, escape, capacity, distance and dragging."""

import re
from copy import deepcopy

VERSION = "library-grapple-1"
SIZES = {
    "крошеч": 0,
    "tiny": 0,
    "малень": 1,
    "небольш": 1,
    "small": 1,
    "средн": 2,
    "medium": 2,
    "больш": 3,
    "large": 3,
    "огром": 4,
    "huge": 4,
    "громад": 5,
    "исполин": 5,
    "gargantuan": 5,
}


def register(spec):
    def integer(lo, hi):
        return {"type": "integer", "minimum": lo, "maximum": hi}

    attack = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "index": integer(0, 29),
            "dc": integer(1, 30),
            "capacity": integer(1, 8),
            "max_size": integer(-1, 5),
            "reach": integer(1, 100),
            "restrained": {"type": "boolean"},
            "advantage_held": {"type": "boolean"},
            "locks": {"type": "array", "items": integer(0, 29), "maxItems": 30},
        },
        "required": [
            "index",
            "dc",
            "capacity",
            "max_size",
            "reach",
            "restrained",
            "advantage_held",
            "locks",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "attacks": {"type": "array", "items": attack, "minItems": 1, "maxItems": 30},
        },
        "required": ["version", "attacks"],
    }
    spec["source_grapple_v1"] = schema
    spec["source_creature"]["properties"]["grapple_v1"] = deepcopy(schema)
    spec["source_creature"]["properties"]["skill_bonuses_v1"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"athletics": integer(-10, 50), "acrobatics": integer(-10, 50)},
    }


def validate(program, actions):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as schema_validate

    schema_validate(program, schemas()["source_grapple_v1"])
    seen = set()
    for row in program["attacks"]:
        if (
            row["index"] in seen
            or row["index"] >= len(actions)
            or not actions[row["index"]]["complete"]
        ):
            raise ValueError("Grapple requires unique complete attack indices")
        seen.add(row["index"])
        if len(set(row["locks"])) != len(row["locks"]) or any(
            i >= len(actions) for i in row["locks"]
        ):
            raise ValueError("Invalid grapple attack locks")


def size(engine, actor):
    if actor == "hero":
        return (
            1
            if engine.state["identity"].get("race_id") in {"halfling", "gnome", "goblin", "kobold"}
            else 2
        )
    value = (
        engine.actor(actor, False)[1].properties.get("library_creature_size", "средний").casefold()
    )
    return next((rank for stem, rank in SIZES.items() if stem in value), 2)


def program(engine, source, index):
    if source == "hero" or source not in engine.actors:
        return None
    return next(
        (
            r
            for r in engine.actor(source, False)[1]
            .properties.get("library_grapple_rules", {})
            .get("attacks", [])
            if r["index"] == index
        ),
        None,
    )


def links(engine):
    state = engine.state.get("source_rules_v3", {})
    rows = state.get("grapples_v1", [])
    if type(rows) is not list or len(rows) > 16000:
        raise ValueError("Invalid saved grapple list")
    if not rows:
        return []
    if any(type(row) is not dict for row in rows):
        raise ValueError("Invalid saved grapple row")
    from rpg_vkr.world_library.source_geometry import distance
    from rpg_vkr.world_library.source_runtime import now

    kept = []
    for row in rows:
        if set(row) != {"source", "target", "index"} or type(row["index"]) is not int:
            raise ValueError("Invalid saved grapple link")
        source, target = row["source"], row["target"]
        if type(source) is not str or type(target) is not str:
            raise ValueError("Invalid saved grapple actor IDs")
        if source not in engine.actors or target != "hero" and target not in engine.actors:
            continue
        rule = program(engine, source, row["index"])
        if rule is None:
            continue
        raw = state.get("conditions", {}).get(source, [])
        if any(
            c["until"] > now(engine)
            and c["kind"] in {"incapacitated", "paralyzed", "petrified", "stunned", "unconscious"}
            for c in raw
        ):
            continue
        if engine.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules_runtime import life

            if (
                life(engine, source).dead
                or life(engine, source).unconscious
                or life(engine, target).dead
            ):
                continue
        elif engine.hp(source) <= 0 or engine.hp(target) <= 0:
            continue
        if distance(engine, source, target) > rule["reach"]:
            continue
        kept.append(row)
    if kept != rows:
        state["grapples_v1"] = kept
        for row in rows:
            if row not in kept:
                engine.events.append(
                    {
                        "kind": "source_grapple_ended",
                        "source": row["source"],
                        "target": row["target"],
                        "attack": row["index"],
                    }
                )
    return kept


def conditions(engine, actor):
    from rpg_vkr.world_library.source_runtime import now, rules

    result = []
    immune = rules(engine, actor).get("condition_immunities", [])
    for row in links(engine):
        if row["target"] != actor:
            continue
        rule = program(engine, row["source"], row["index"])
        for kind in ["grappled", "restrained"] if rule["restrained"] else ["grappled"]:
            if kind in immune:
                continue
            result.append(
                {
                    "kind": kind,
                    "source": row["source"],
                    "until": now(engine) + 1,
                    "repeat": "none",
                    "ability": "",
                    "dc": 0,
                    "magical": False,
                }
            )
    return result


def allowed(engine, source, target, index):
    held = [r for r in links(engine) if r["source"] == source]
    locked = [r for r in held if index in program(engine, source, r["index"])["locks"]]
    if locked and target not in {r["target"] for r in locked}:
        return False
    rule = program(engine, source, index)
    if rule:
        used = [r for r in held if r["index"] == index]
        if len(used) >= rule["capacity"] and not any(r["target"] == target for r in used):
            return False
    return True


def advantage(engine, source, target, index):
    return any(
        r["source"] == source
        and r["target"] == target
        and program(engine, source, r["index"])["advantage_held"]
        and index == r["index"]
        for r in links(engine)
    )


def apply(engine, source, target, index):
    rule = program(engine, source, index)
    if rule is None:
        return
    from rpg_vkr.world_library.source_geometry import distance
    from rpg_vkr.world_library.source_runtime import incapacitated, rules

    if incapacitated(engine, source) or distance(engine, source, target) > rule["reach"]:
        return

    if "grappled" in rules(engine, target).get("condition_immunities", []):
        engine.events.append(
            {"kind": "source_condition_immune", "actor": target, "condition": "grappled"}
        )
        return
    maximum = rule["max_size"] if rule["max_size"] >= 0 else min(5, size(engine, source) + 1)
    if size(engine, target) > maximum:
        return
    if engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import life

        if life(engine, target).dead:
            return
    elif engine.hp(target) <= 0:
        return
    existing = links(engine)
    if any(r == {"source": source, "target": target, "index": index} for r in existing):
        return
    if not allowed(engine, source, target, index):
        return
    if len(existing) >= 16000:
        raise ValueError("World grapple safety bound")
    engine.state["source_rules_v3"]["grapples_v1"] = existing + [
        {"source": source, "target": target, "index": index}
    ]
    engine.events.append(
        {
            "kind": "source_grapple",
            "source": source,
            "target": target,
            "attack": index,
            "dc": rule["dc"],
        }
    )


def escape(engine, args, actor="hero"):
    from rpg_vkr.world_library import source_runtime

    source = args.get("source")
    ability = args.get("ability")
    if type(source) is not str or ability not in {"strength", "dexterity"}:
        raise ValueError("Specify source and Strength or Dexterity")
    if source_runtime.incapacitated(engine, actor):
        raise ValueError("Incapacitated actor cannot escape")
    candidates = [r for r in links(engine) if r["source"] == source and r["target"] == actor]
    if "attack_index" in args:
        if type(args["attack_index"]) is not int:
            raise ValueError("Invalid grapple index")
        candidates = [r for r in candidates if r["index"] == args["attack_index"]]
    if not candidates:
        raise ValueError("No such active grapple")
    link = min(candidates, key=lambda r: r["index"])
    dc = program(engine, source, link["index"])["dc"]
    task = "athletics" if ability == "strength" else "acrobatics"
    if actor == "hero":
        success = engine.check(task, dc)
    else:
        from rpg_vkr.domain.character import ability_modifier
        from rpg_vkr.domain.owner_rules import check

        properties = engine.actor(actor, False)[1].properties
        bonus = properties.get("library_check_bonuses", {}).get(
            task, ability_modifier(properties.get(ability, 10))
        )
        natural = source_runtime.roll_d20(
            engine, -1 if source_runtime.has(engine, actor, "poisoned") else 0, "Освобождение NPC"
        )
        exhaustion = 0
        if engine.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules_runtime import life

            exhaustion = life(engine, actor).exhaustion
        if engine.state.get("owner_rules_policy") == 1:
            result = check(natural, bonus, dc, exhaustion=exhaustion, partial=False)
            success = result["succeeded"]
            if result["complication"]:
                engine.owner_complication_minutes = (
                    getattr(engine, "owner_complication_minutes", 0) + 1
                )
        else:
            success = natural + bonus >= dc
    if success:
        engine.state["source_rules_v3"]["grapples_v1"].remove(link)
    engine.events.append(
        {
            "kind": "source_escape",
            "actor": actor,
            "source": source,
            "attack": link["index"],
            "success": success,
        }
    )
    return success


def drag_speed(engine, actor, base):
    held = [r for r in links(engine) if r["source"] == actor]
    return (
        base // 2
        if any(size(engine, r["target"]) > size(engine, actor) - 2 for r in held)
        else base
    )


def moved(engine, actor, before, after, held):
    from rpg_vkr.world_library.source_geometry import positions, valid

    delta = [b - a for a, b in zip(before, after, strict=True)]
    for target in sorted({r["target"] for r in held if r["source"] == actor}):
        point = positions(engine)[target]
        destination = [a + b for a, b in zip(point["point"], delta, strict=True)]
        valid(destination)
        point["point"] = destination
        point["origin"] = "engine-grapple-drag"
        engine.events.append(
            {"kind": "source_drag", "actor": actor, "target": target, "to": point["point"]}
        )


def extract(stat, actions):
    from rpg_vkr.world_library.creature_actions import damage_components, text
    from rpg_vkr.world_library.source_extract import action_matches

    result = []
    for raw in stat.get("действия", []):
        if not isinstance(raw, dict):
            continue
        name = text(raw.get("название"))
        indices = [i for i, a in enumerate(actions) if a["name"] == name]
        if len(indices) != 1:
            continue
        index = indices[0]
        body = text(raw.get("описание")).casefold().replace("ё", "е")
        if "рукопашная атака" not in body or "попадание:" not in body:
            continue
        reach = re.search(r"досягаемость\s+(\d+)", body)
        if not reach or not 1 <= int(reach[1]) <= 100:
            continue
        body = body.split("попадание:", 1)[1].strip()
        maximum = -1
        match = re.fullmatch(
            r"(.+?)(?:,? и |\. )цель (?:становится )?схвачен[а-я]* "
            r"\(сл высвобождения (\d+)\)(.*)",
            body,
        )
        if match:
            damage, dc, tail = match[1], int(match[2]), match[3]
        else:
            match = re.fullmatch(
                r"(.+?)[.,]\s*(?:и )?если "
                r"(?:цель\s*(?:—|-)?\s*(?:это )?существо|целью является существо) "
                r"(?:(?:с размером не больше )?"
                r"((?:среднего|большого|огромного|громадного|исполинского))"
                r"(?: размера)?(?: или (?:меньшего размера|меньше|меньше размера))?), "
                r"(?:то )?(?:она|оно) становится схваченн(?:ой|ым) \(сл высвобождения (\d+)\)(.*)",
                body,
            )
            if not match:
                continue
            damage, word, dc, tail = match[1], match[2], int(match[3]), match[4]
            maximum = next(rank for stem, rank in SIZES.items() if stem in word)
        components, complete = damage_components(damage.strip(" ,."))
        if not complete or not 1 <= dc <= 30:
            continue
        tail = tail.strip(" .")
        capacity = 1
        restrained = False
        advantage_held = False
        locks = []
        # Every tail clause must be covered; ongoing damage and saving throws stay pending.
        restrained_clause = re.match(
            r"и опутано до тех пор, пока этот захват не закончится\.?\s*", tail
        )
        if restrained_clause:
            restrained = True
            tail = tail[restrained_clause.end() :].strip(" .")
        cap = re.fullmatch(
            r"у [а-я -]{1,100} (две|три|четыре|шесть|восемь|[1-8]) [а-я -]{1,40}, "
            r"(?:каждой из них он|каждая из которых|каждая из них) может схватить "
            r"(?:одну цель|одно существо)",
            tail,
        )
        single = re.fullmatch(
            r"одновременно [а-я -]{1,100} может "
            r"(?:быть схвачено только одно существо|схватить только одно существо)",
            tail,
        )
        constrain = re.fullmatch(
            r"пока цель схвачена, она (?:так же )?опутана, и [а-я -]{1,100} "
            r"не может (?:использовать (?:свою )?атаку )?([а-я -]+) "
            r"(?:на другую цель|против другого существа|другую цель)",
            tail,
        )
        bite = re.fullmatch(
            r"пока цель схвачена, [а-я -]{1,100} может кусать только ее, "
            r"но зато атаки совершает с преимуществом",
            tail,
        )
        if cap:
            capacity = {"две": 2, "три": 3, "четыре": 4, "шесть": 6, "восемь": 8}.get(
                cap[1], int(cap[1]) if cap[1].isdigit() else 1
            )
        elif constrain:
            restrained = True
            phrases = re.split(r"\s+или\s+", constrain[1])
            for phrase in phrases:
                found = [i for i, a in enumerate(actions) if action_matches(a["name"], phrase)]
                if len(found) != 1:
                    break
                locks.append(found[0])
            if len(locks) != len(phrases):
                continue
        elif bite and name.casefold() == "укус":
            locks = [index]
            advantage_held = True
        elif tail and not single:
            continue
        actions[index]["components"] = components
        actions[index]["element"] = components[0]["element"]
        actions[index]["complete"] = True
        result.append(
            {
                "index": index,
                "dc": dc,
                "capacity": capacity,
                "max_size": maximum,
                "reach": int(reach[1]),
                "restrained": restrained,
                "advantage_held": advantage_held,
                "locks": locks,
            }
        )
    return {"version": VERSION, "attacks": result} if result else None


def perform_escape(engine, args):
    from rpg_vkr.world_library import source_runtime
    from rpg_vkr.world_library.source_geometry import move, positions, square, valid

    destination = args.get("position")
    if destination is not None:
        if not engine.state["battle"]:
            raise ValueError("Escape movement requires an encounter")
        valid(destination)
        point = positions(engine)["hero"]["point"]
        base = drag_speed(engine, "hero", 15 if source_runtime.has(engine, "hero", "prone") else 30)
        if engine.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules_runtime import life

            base = max(0, base - 5 * life(engine).exhaustion)
        if square(point, destination) > base * base:
            raise ValueError("Escape destination exceeds movement budget")
        if point[2] != destination[2] and not engine.status_power("hero", "flight"):
            raise ValueError("Vertical escape requires flight")
    success = escape(engine, args)
    if success and destination is not None:
        speed = source_runtime.speed(engine, "hero", 30)
        if engine.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules_runtime import life

            speed = max(0, speed - 5 * life(engine).exhaustion)
        if speed:
            move(engine, "hero", destination, speed)
        else:
            engine.events.append({"kind": "source_escape_movement_blocked", "actor": "hero"})
    return success


def release(engine, source):
    current = links(engine)
    removed = [r for r in current if r["source"] == source]
    if removed:
        engine.state["source_rules_v3"]["grapples_v1"] = [
            r for r in current if r["source"] != source
        ]
        for row in removed:
            engine.events.append(
                {
                    "kind": "source_grapple_release",
                    "source": source,
                    "target": row["target"],
                    "attack": row["index"],
                }
            )
