"""Bounded authored faction policies and public-event gossip; no model authority.

Budgets are finite campaign-start resources. Projects spend funds, donations/taxes
transfer existing coins. NPC gossip can only transmit engine-confirmed victories.
"""

from copy import deepcopy
from dataclasses import replace

from rpg_vkr.domain.gameplay import available
from rpg_vkr.domain.interactions import identifier, label

VERSION = "world-factions-1"
PROJECTS = {"security": ("patrol", 120, 2), "prosperity": ("workshop", 100, 1)}


def _actors(catalog):
    definitions = {d.id: d for d in catalog.definitions}
    return [
        (e, definitions[e.definition_id])
        for e in catalog.entities
        if definitions[e.definition_id].kind == "actor"
    ]


def initialize(state, catalog, scene):
    state = deepcopy(state)
    if catalog is None:
        return state
    factions = state["factions_v3"]
    for entity, definition in _actors(catalog):
        id = definition.properties.get("faction_id", "")
        if not id:
            continue
        identifier(id)
        existing = factions.get(id)
        name = definition.properties.get(
            "faction_name", existing["name"] if existing else id.replace("_", " ")
        )
        goal = definition.properties.get(
            "faction_goal", existing["goal"] if existing else "prosperity"
        )
        label(name, 100)
        if not isinstance(goal, str) or goal not in PROJECTS:
            raise ValueError("Цель фракции должна быть security или prosperity.")
        if existing and (name, goal) != (existing["name"], existing["goal"]):
            raise ValueError("Нельзя переписать установленное имя или цель фракции.")
        if existing is None:
            if len(factions) >= 20:
                raise ValueError("В прототипе поддержано до20 фракций.")
            existing = factions[id] = {
                "id": id,
                "name": name,
                "goal": goal,
                "members": [],
                "treasury_cp": 1000,
                "spent_cp": 0,
                "influence": 10,
                "reputation": 0,
                "last_day": state["minute"] // 1440,
                "last_public": "Объединение известно по его представителям.",
            }
        if entity.id not in existing["members"]:
            existing["members"].append(entity.id)
            existing["members"].sort()
    return remember_visible(state, catalog, scene)


def living(catalog, id):
    pair = next(((e, d) for e, d in _actors(catalog) if e.id == id), None)
    return bool(pair and (pair[0].state or {}).get("hp", pair[1].properties["hp_max"]) > 0)


def _awake(catalog, state, id):
    definition = next((d for e, d in _actors(catalog) if e.id == id), None)
    return living(catalog, id) and available(state, id, definition)


def can_speak(catalog, id):
    definition = next((d for e, d in _actors(catalog) if e.id == id), None)
    return bool(
        definition
        and (
            "creatures" not in definition.categories
            or definition.properties.get("can_speak") is True
        )
    )


def remember_visible(state, catalog, scene):
    # Only current contact refreshes the player's public view; no hidden balances.
    if catalog is None:
        return state
    here = {
        a.id for a in scene.actor_refs if a.place == scene.current and _awake(catalog, state, a.id)
    }
    for id, faction in state["factions_v3"].items():
        if here.intersection(faction["members"]):
            state["known_factions"][id] = {
                "id": id,
                "name": faction["name"],
                "goal": faction["goal"],
                "reputation": faction["reputation"],
                "last_seen_minute": state["minute"],
                "news": faction["last_public"],
            }
    return state


def simulate(state, catalog, scene):
    """Batch daily projects and one bounded gossip pass, returning explicit events."""
    events = []
    if catalog is None:
        return state, scene, events
    places = [p.id for p in scene.places]
    for id in sorted(state["factions_v3"]):
        faction = state["factions_v3"][id]
        project, cost, gain = PROJECTS[faction["goal"]]
        for day in range(faction["last_day"] + 1, state["minute"] // 1440 + 1):
            members = [m for m in faction["members"] if living(catalog, m) and m != state["active"]]
            if members and faction["treasury_cp"] >= cost:
                faction["treasury_cp"] -= cost
                faction["spent_cp"] += cost
                faction["influence"] = min(100, faction["influence"] + gain)
                faction["last_public"] = (
                    "Усилились патрули объединения."
                    if project == "patrol"
                    else "Мастера продолжили общий производственный проект."
                )
                events.append(
                    {
                        "kind": "faction_project",
                        "faction": id,
                        "day": day,
                        "project": project,
                        "spent_cp": cost,
                    }
                )
                if project == "patrol" and places:
                    destination = places[day % len(places)]
                    for member in members:
                        npc = state["npc"].setdefault(member, {"heard": [], "source": "hero"})
                        npc["work"] = destination
                    scene = replace(
                        scene,
                        actors=tuple(
                            replace(a, place=destination)
                            if a.id in members and _awake(catalog, state, a.id)
                            else a
                            for a in scene.actor_refs
                        ),
                    )
        faction["last_day"] = state["minute"] // 1440
    # Two NPCs must actually be co-located, alive and awake. No global knowledge merge.
    active = [
        a
        for a in scene.actor_refs
        if a.id != state["active"] and _awake(catalog, state, a.id) and can_speak(catalog, a.id)
    ]
    existing = {a.id: list(state["npc"].get(a.id, {}).get("knowledge", [])) for a in active}
    for recipient in active:
        npc = state["npc"].setdefault(recipient.id, {"heard": [], "source": "hero"})
        known = {k["event"] for k in npc.get("knowledge", [])}
        for source in active:
            if source.id == recipient.id or source.place != recipient.place:
                continue
            for fact in existing[source.id]:
                if fact["event"] not in state["victories"] or fact["event"] in known:
                    continue
                copied = {
                    "event": fact["event"],
                    "kind": "heard",
                    "source": source.id,
                    "confidence": max(10, min(75, fact["confidence"] - 10)),
                }
                npc.setdefault("knowledge", []).append(copied)
                if fact["event"] not in npc["heard"]:
                    npc["heard"].append(fact["event"])
                known.add(fact["event"])
                events.append(
                    {
                        "kind": "information_transferred",
                        "source": source.id,
                        "recipient": recipient.id,
                        "event": fact["event"],
                        "minute": state["minute"],
                        "confidence": copied["confidence"],
                    }
                )
    state["simulation_seq"] += len(events)
    return remember_visible(state, catalog, scene), scene, events


def tax_recipient(state):
    security = [f for f in state["factions_v3"].values() if f["goal"] == "security"]
    prosperity = [
        f["influence"] for f in state["factions_v3"].values() if f["goal"] == "prosperity"
    ]
    if not security:
        return None
    chosen = max(security, key=lambda f: (f["influence"], f["id"]))
    return chosen if chosen["influence"] >= max(prosperity or [10]) + 3 else None


def contact(state, catalog, scene, faction_id):
    faction = state["factions_v3"].get(faction_id)
    if faction is None or faction_id not in state["known_factions"]:
        raise ValueError("Фракция пока не известна герою.")
    if not any(
        a.place == scene.current and a.id in faction["members"] and _awake(catalog, state, a.id)
        for a in scene.actor_refs
    ):
        raise ValueError("Рядом нет доступного представителя фракции.")
    return faction
