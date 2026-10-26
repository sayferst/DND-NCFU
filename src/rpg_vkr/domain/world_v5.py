"""Finite sandbox world: calendar, needs, labor, supplies, diplomacy and local reports."""

from dataclasses import replace

from rpg_vkr.domain.content_v5 import make_item

VERSION = "living-world-1"


def initialize(state, catalog, scene):
    if state.get("living_world") is None:
        state["living_world"] = {
            "version": VERSION,
            "day": state["minute"] // 1440,
            "nodes": {},
            "residents": {},
            "stocks": {},
            "relations": {},
            "territories": {},
            "observed": {},
            "sequence": 0,
        }
    world = state["living_world"]
    for place in scene.places:
        world["nodes"].setdefault(place.id, {"wood": 20, "iron": 20, "herb": 10})
    if catalog:
        definitions = {d.id: d for d in catalog.definitions}
        for entity in catalog.entities:
            if definitions[entity.definition_id].kind == "actor":
                world["residents"].setdefault(
                    entity.id,
                    {"food": 3, "hunger": 0, "fatigue": 0, "goal": "work", "knowledge": []},
                )
    for faction in state["factions_v3"]:
        world["stocks"].setdefault(faction, {"wood": 10, "iron": 10, "herb": 10, "food": 3})
    return world


def calendar(minute):
    day = minute // 1440
    return {
        "year": 1 + day // 360,
        "month": 1 + day // 30 % 12,
        "day": 1 + day % 30,
        "season": (day // 90) % 4,
        "hour": minute // 60 % 24,
        "minute": minute % 60,
    }


def advance(state, catalog, scene):
    world = initialize(state, catalog, scene)
    if not catalog:
        return state, catalog, scene, []
    events = []
    entities = {e.id: e for e in catalog.entities}
    definitions = {d.id: d for d in catalog.definitions}
    refs = {r.id: r for r in scene.actor_refs}
    engaged = set((state.get("battle") or {}).get("order", []))
    day_now = state["minute"] // 1440
    for day in range(world["day"] + 1, day_now + 1):
        for faction_id, faction in sorted(state["factions_v3"].items()):
            stock = world["stocks"][faction_id]
            members = [
                id
                for id in faction["members"]
                if id in entities
                and (entities[id].state or {}).get("hp", 1) > 0
                and id not in engaged
            ]
            if members and stock["wood"] and stock["herb"]:
                stock["wood"] -= 1
                stock["herb"] -= 1
                stock["food"] += 3
                events.append(
                    {
                        "kind": "production",
                        "faction": faction_id,
                        "day": day,
                        "inputs": {"wood": 1, "herb": 1},
                        "food": 3,
                    }
                )
            for member in members:
                if faction["treasury_cp"] >= 2:
                    faction["treasury_cp"] -= 2
                    entity = entities[member]
                    entities[member] = replace(
                        entity,
                        state=(entity.state or {})
                        | {"gold_cp": (entity.state or {}).get("gold_cp", 0) + 2},
                    )
                    events.append({"kind": "wage", "actor": member, "amount_cp": 2, "day": day})
            traders = [
                id
                for id in members
                if definitions[entities[id].definition_id].properties.get("class")
                in {"merchant", "trader", "shopkeeper"}
            ]
            if traders and stock["herb"] >= 2:
                stock["herb"] -= 2
                id = f"production_{day}_{faction_id}"
                state["items"].append(make_item(id, "potion", traders[0]))
        for id, resident in sorted(world["residents"].items()):
            entity = entities.get(id)
            if not entity or id in engaged or (entity.state or {}).get("hp", 1) <= 0:
                continue
            faction = next((f for f in state["factions_v3"].values() if id in f["members"]), None)
            stock = world["stocks"].get(faction["id"]) if faction else None
            if resident["food"]:
                resident["food"] -= 1
                resident["hunger"] = max(0, resident["hunger"] - 1)
            elif stock and stock["food"]:
                stock["food"] -= 1
                resident["hunger"] = 0
            elif id in refs and world["nodes"][refs[id].place]["herb"]:
                world["nodes"][refs[id].place]["herb"] -= 1
                resident["hunger"] = 0
                events.append({"kind": "forage", "actor": id, "day": day})
            else:
                resident["hunger"] += 1
            resident["goal"] = "seek_food" if resident["hunger"] else "work"
            resident["fatigue"] = min(10, resident["fatigue"] + 1) if resident["hunger"] else 0
            if resident["hunger"] >= 7:
                hp = max(
                    0,
                    (entity.state or {}).get(
                        "hp", definitions[entity.definition_id].properties["hp_max"]
                    )
                    - 1,
                )
                entities[id] = replace(
                    entity,
                    state=(entity.state or {}) | {"hp": hp, **({"life": "dead"} if not hp else {})},
                )
                events.append({"kind": "starvation", "actor": id, "day": day, "hp": hp})
            if (entities[id].state or {}).get("hp", 1) > 0 and resident["hunger"] and id in refs:
                traders = [
                    r
                    for r in refs.values()
                    if definitions[entities[r.id].definition_id].properties.get("class")
                    == "merchant"
                    and (entities[r.id].state or {}).get("hp", 1) > 0
                ]
                if traders:
                    target = sorted(traders, key=lambda r: r.id)[0]
                    refs[id] = replace(refs[id], place=target.place)
                    state["npc"].setdefault(id, {"heard": [], "source": "hero"})["work"] = (
                        target.place
                    )
        factions = sorted(state["factions_v3"])
        for i, left in enumerate(factions):
            for right in factions[i + 1 :]:
                key = left + ":" + right
                relation = world["relations"].setdefault(key, 0)
                a, b = state["factions_v3"][left], state["factions_v3"][right]
                if a["goal"] != b["goal"]:
                    relation = max(-100, relation - 1)
                world["relations"][key] = relation
                if relation <= -30 and min(a["treasury_cp"], b["treasury_cp"]) >= 50:
                    a["treasury_cp"] -= 50
                    b["treasury_cp"] -= 50
                    a["spent_cp"] += 50
                    b["spent_cp"] += 50
                    winner = max((a, b), key=lambda f: (f["influence"], f["id"]))
                    places = sorted(world["nodes"])
                    place = places[day % len(places)]
                    world["territories"][place] = winner["id"]
                    events.append(
                        {
                            "kind": "territory_conflict",
                            "day": day,
                            "place": place,
                            "winner": winner["id"],
                        }
                    )
        # Knowledge needs a real source/location; the entire event ledger is private.
        for event in [e for e in events if e["day"] == day]:
            place = event.get("place") or (
                refs[event["actor"]].place if event.get("actor") in refs else None
            )
            if place:
                for id, ref in refs.items():
                    if (
                        ref.place == place
                        and id not in engaged
                        and (entities[id].state or {}).get("hp", 1) > 0
                    ):
                        resident = world["residents"][id]
                        resident["knowledge"].append(
                            {"kind": "observed", "event": event["kind"], "day": day, "place": place}
                        )
                        resident["knowledge"] = resident["knowledge"][-30:]
    world["day"] = day_now
    world["sequence"] += len(events)
    world["calendar"] = calendar(state["minute"])
    for id, ref in refs.items():
        if (entities[id].state or {}).get("hp", 1) <= 0:
            world["observed"].pop(id, None)
            continue
        if (
            ref.place == scene.current
            and id not in engaged
            and (entities[id].state or {}).get("hp", 1) > 0
        ):
            world["observed"][id] = {
                "name": definitions[entities[id].definition_id].name,
                "goal": world["residents"][id]["goal"],
                "minute": state["minute"],
                "reports": world["residents"][id]["knowledge"][-3:],
            }
    catalog = replace(catalog, entities=tuple(entities[e.id] for e in catalog.entities))
    scene = replace(scene, actors=tuple(refs[r.id] for r in scene.actor_refs))
    return state, catalog, scene, events
