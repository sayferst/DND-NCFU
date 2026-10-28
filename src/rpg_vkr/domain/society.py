"""Revision-three finite settlements, transport, livelihoods and individual life cycles."""

from collections import deque
from dataclasses import replace

from rpg_vkr.domain import catalog_world as legacy
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.causal_world import BIOMES
from rpg_vkr.domain.interactions import ActorRef, identifier, label

JOBS = {
    "miner": "mat_0_0",
    "forester": "mat_1_0",
    "farmer": "mat_2_0",
    "weaver": "mat_3_0",
    "hunter": "mat_4_0",
    "quarrier": "mat_5_0",
    "glassmaker": "mat_8_0",
    "smith": "mat_0_0",
    "alchemist": "mat_2_0",
}


def initialize(e):
    w = e.state["living_world"]
    new = "society" not in w
    s = w.setdefault(
        "society",
        {
            "version": "settlement-3",
            "sequence": 0,
            "places": {},
            "people": {},
            "cargo": [],
            "ledger": [],
            "last": {},
        },
    )
    for p in e.scene.places:
        if p.id in s["places"]:
            continue
        habitat = next(
            (b for word, b in BIOMES if word in (p.name + " " + p.description).casefold()), 9
        )
        s["places"][p.id] = {
            "habitat": habitat,
            "water": 12,
            "soil": 60,
            "plants_cap": 40,
            "herbivores": 8,
            "predators": 2,
            "animal_energy": 12,
            "predator_hunger": 0,
            "prey_hunger": 0,
            "population_cap": 24,
            "deposits": {f"mat_{i}_0": 120 for i in (0, 5, 6, 7, 8, 9)}
            | ({"mat_1_0": 120} if habitat == 0 else {}),
            "price": 100,
            "weather_cause": None,
        }
    for id, ref in e.refs.items():
        if id in s["people"]:
            continue
        spec = e.definitions[e.actors[id].definition_id]
        age = spec.properties.get("age", 20)
        age = age if type(age) is int and 0 <= age <= 200 else 20
        civilian = not (e.actors[id].state or {}).get("encounter_source") and (
            "npcs" in spec.categories
            or spec.properties.get("class")
            in (
                *JOBS,
                "merchant",
                "trader",
                "shopkeeper",
                "resident",
                "artisan",
                "guard",
                "dependent",
            )
        )
        s["people"][id] = {
            "age_days": age * 365,
            "civilian": bool(civilian),
            "born_day": w["day"],
            "last_day": w["day"],
            "known_places": {
                ref.place: {"food": w["stocks"][ref.place]["food"], "seen_day": w["day"]}
            },
            "destination": None,
            "route": [],
            "mature": age >= 18,
        }
    factions = e.state.setdefault("factions_v3", {})
    for id, ref in e.refs.items():
        spec = e.definitions[e.actors[id].definition_id]
        group = spec.properties.get("faction_id")
        if not group:
            continue
        identifier(group)
        name = spec.properties.get(
            "faction_name",
            factions[group]["name"] if group in factions else group.replace("_", " "),
        )
        goal = spec.properties.get(
            "faction_goal", factions[group]["goal"] if group in factions else "prosperity"
        )
        label(name, 100)
        if goal not in ("security", "prosperity"):
            raise ValueError("Неизвестная цель объединения.")
        if group in factions and (name, goal) != (factions[group]["name"], factions[group]["goal"]):
            raise ValueError("Нельзя переписать установленное объединение.")
        if group not in factions:
            if len(factions) >= 20:
                continue
            factions[group] = {
                "id": group,
                "name": spec.properties.get("faction_name", group),
                "goal": spec.properties.get("faction_goal", "prosperity"),
                "members": [],
                "treasury_cp": 0,
                "spent_cp": 0,
                "influence": 10,
                "reputation": 0,
                "last_day": w["day"],
                "last_public": "Объединение известно по его представителям.",
            }
        faction = factions[group]
        if id not in faction["members"]:
            contribution = min(25, (e.actors[id].state or {}).get("gold_cp", 0))
            if contribution:
                legacy._wallet(e, id, -contribution)
                faction["treasury_cp"] += contribution
            faction["members"].append(id)
            emit(e, "faction_member", ref.place, actor=id, faction=group, money=contribution)
        if ref.place == e.scene.current:
            e.state["known_factions"][group] = {
                "id": group,
                "name": faction["name"],
                "goal": faction["goal"],
                "reputation": faction["reputation"],
                "last_seen_minute": e.state["minute"],
                "news": faction["last_public"],
            }
    if new:
        # Geological reserves are finite deposits, never an unlimited shop refill.
        s["genesis_coins"] = (
            w["treasury_cp"]
            + sum((a.state or {}).get("gold_cp", 0) for a in e.actors.values())
            + e.state["copper"]
            + e.world.gold * 100
            + sum(f["treasury_cp"] for f in factions.values())
        )
    w["price_percent"] = s["places"][e.scene.current]["price"]
    return s


def emit(e, kind, place, *, cause=None, **details):
    w = e.state["living_world"]
    s = w["society"]
    s["sequence"] += 1
    row = {
        "id": f"society_{s['sequence']}",
        "kind": kind,
        "place": place,
        "minute": e.state["minute"],
        "cause": cause,
        **details,
    }
    s["ledger"].append(row)
    s["ledger"][:] = s["ledger"][-600:]
    s["last"][place] = row["id"]
    # Observations carry witnessed actions, not hidden balances of remote stores or wallets.
    public = {
        k: v
        for k, v in row.items()
        if k
        in (
            "id",
            "kind",
            "place",
            "minute",
            "cause",
            "actor",
            "destination",
            "resource",
            "quantity",
            "shipment",
            "weather",
            "reporter",
            "reported_event",
            "confirmed",
        )
    }
    w["observed"].setdefault(place, []).append(public)
    w["observed"][place] = w["observed"][place][-30:]
    e.state["world_log"].append(public)
    e.state["world_log"][:] = e.state["world_log"][-200:]
    for id, ref in e.refs.items():
        if ref.place == place and id in w["residents"] and e.hp(id) > 0:
            r = w["residents"][id]
            r["knowledge"].append(row["id"])
            r["knowledge"][:] = r["knowledge"][-50:]
    if e.scene.current == place:
        e.events.append(public)
        messages = {
            "shipment_arrived": "В поселение прибыла поставка припасов.",
            "shipment_delayed": "Поставка задерживается: дорога закрыта.",
            "resident_born": "В поселении появился ребёнок.",
            "resident_died": "Житель поселения погиб от голода.",
            "predator_starved": "Следов хищников стало меньше: зверям не хватает добычи.",
        }
        if kind in messages:
            e.text.append(messages[kind])
        if kind == "climate_changed":
            e.text.append(
                "Погода: "
                + {
                    "clear": "ясно",
                    "rain": "дождь",
                    "drought": "засуха",
                    "fog": "туман",
                    "storm": "буря",
                    "thaw": "оттепель",
                }.get(details.get("weather"), "переменилась")
                + "."
            )
    return row["id"]


def neighbors(e, place):
    p = e.scene.place(place)
    return sorted(q.id for q in e.scene.places if q.parent == place or q.id == p.parent)


def route(e, source, destination):
    if source == destination:
        return []
    blocked = e.state["living_world"].get("blocked_until", {})
    todo = deque([(source, [])])
    seen = {source}
    while todo:
        here, path = todo.popleft()
        for p in neighbors(e, here):
            if p in seen or max(blocked.get(here, 0), blocked.get(p, 0)) > e.state["minute"]:
                continue
            if p == destination:
                return path + [p]
            seen.add(p)
            todo.append((p, path + [p]))
    return None


def hourly(e):
    w = e.state["living_world"]
    s = initialize(e)
    hour = e.state["minute"] // 60 % 24
    engaged = set((e.state.get("battle") or {}).get("order", []))
    for id, resident in sorted(w["residents"].items()):
        if id not in e.refs or id in engaged or e.hp(id) <= 0:
            continue
        p = e.refs[id].place
        person = s["people"][id]
        if not person["civilian"] or not person["mature"]:
            continue
        person["known_places"][p] = {"food": w["stocks"][p]["food"], "seen_day": w["day"]}
        destination = resident["work"] if 8 <= hour < 18 else resident["home"]
        if resident["hunger"] >= 3:
            # Only prior observations can motivate a food migration; unseen stocks never guide it.
            known = [
                q
                for q, v in person["known_places"].items()
                if q != p and v["food"] > 0 and w["day"] - v["seen_day"] <= 7
            ]
            destination = sorted(known)[0] if known else next(iter(neighbors(e, p)), p)
        steps = route(e, p, destination)
        person["destination"] = destination
        person["route"] = steps or []
        if steps and legacy.move_actor(e, id, steps[0]):
            emit(e, "resident_journey", p, actor=id, destination=steps[0], cause=s["last"].get(p))
            for child, info in s["people"].items():
                if (
                    not info["mature"]
                    and id in info.get("parents", [])
                    and child in e.refs
                    and e.refs[child].place == p
                    and e.hp(child) > 0
                ):
                    legacy.move_actor(e, child, steps[0])
                    emit(
                        e,
                        "family_journey",
                        p,
                        actor=child,
                        destination=steps[0],
                        cause=s["last"].get(p),
                    )


def _tool(e, id):
    return next(
        (
            i
            for i in e.state["items"]
            if i["owner"] == id
            and i.get("template") in content.load()
            and content.row(i["template"]).get("capability") == "tools"
            and i["durability"] > 0
        ),
        None,
    )


def livelihood(e, id, place):
    w = e.state["living_world"]
    s = w["society"]
    local = s["places"][place]
    stock = w["stocks"][place]
    nodes = w["nodes"][place]
    resident = w["residents"][id]
    job = resident["job"]
    tool = _tool(e, id)
    if stock["food"] < (24 if job == "farmer" else 12):
        source = stock if stock.get("mat_2_0", 0) > 0 else nodes
        if source.get("mat_2_0", 0) > 0:
            source["mat_2_0"] -= 1
            stock["food"] += 3
            emit(
                e,
                "food_cooked",
                place,
                cause=s["last"].get(place),
                actor=id,
                resource="mat_2_0",
                consumed=1,
                food_produced=3,
            )
    resource = JOBS.get(job)
    if job in ("merchant", "trader", "shopkeeper", "artisan"):
        resource = min((f"mat_{i}_0" for i in range(10)), key=lambda k: (stock[k], k))
    if resource and (tool or resource in ("mat_1_0", "mat_2_0", "mat_3_0")):
        if tool and tool["durability"] <= 2 and stock["mat_0_0"]:
            stock["mat_0_0"] -= 1
            tool["durability"] = min(tool["durability_cap"], tool["durability"] + 10)
            emit(
                e,
                "work_tools_repaired",
                place,
                actor=id,
                resource="mat_0_0",
                consumed=1,
                cause=s["last"].get(place),
            )
        amount = min(2, nodes.get(resource, 0))
        if not amount and local["deposits"].get(resource, 0):
            amount = min(2, local["deposits"][resource])
            local["deposits"][resource] -= amount
            nodes[resource] = nodes.get(resource, 0) + amount
            emit(
                e,
                "deposit_opened",
                place,
                actor=id,
                resource=resource,
                quantity=amount,
                deposit_after=local["deposits"][resource],
                cause=s["last"].get(place),
            )
        amount = min(2, nodes.get(resource, 0))
        if amount:
            nodes[resource] -= amount
            stock[resource] += amount
            if tool:
                tool["durability"] -= 1
            emit(
                e,
                "professional_output",
                place,
                actor=id,
                resource=resource,
                quantity=amount,
                cause=s["last"].get(place),
                node_after=nodes[resource],
                stock_after=stock[resource],
            )
            if w["treasury_cp"] >= 3:
                w["treasury_cp"] -= 3
                legacy._wallet(e, id, 3)
                emit(e, "work_paid", place, actor=id, money=3, cause=s["last"].get(place))
    npc_production(e, id, place, tool)
    if job not in ("merchant", "trader", "shopkeeper"):
        return
    for resource in (f"mat_{i}_0" for i in range(10)):
        held = sum(
            i["quantity"]
            for i in e.state["items"]
            if i["owner"] == id and i.get("template") == resource
        )
        amount = min(2 - held, stock[resource])
        price = content.row(resource)["price_cp"]
        amount = min(amount, (e.actors[id].state or {}).get("gold_cp", 0) // max(1, price))
        if amount <= 0:
            continue
        cost = amount * price
        assert legacy._wallet(e, id, -cost)
        w["treasury_cp"] += cost
        stock[resource] -= amount
        item = e.add_item(resource, amount, owner=id)
        emit(
            e,
            "shop_supplied",
            place,
            actor=id,
            resource=resource,
            quantity=amount,
            item=item["id"],
            money=cost,
            cause=s["last"].get(place),
        )


def npc_production(e, id, place, tool):
    job = e.state["living_world"]["residents"][id]["job"]
    if not tool or tool["durability"] <= 0 or job not in ("smith", "artisan", "alchemist"):
        return
    choices = (
        ("use_potions_3_0", "use_dressings_0_0")
        if job == "alchemist"
        else ("use_ammunition_0_0", "gear_sword_0_0", "gear_dagger_0_0")
    )
    for key in choices:
        if sum(
            i["quantity"] for i in e.state["items"] if i["owner"] == id and i.get("template") == key
        ) >= (12 if key.startswith("use_ammunition") else 2):
            continue
        recipe = next(r for r in content.available("recipe") if key in r["outputs"])
        station = any(
            e.definitions[a.definition_id].properties.get("station") == recipe["station"]
            and a.parent_id == place
            and e.definitions[a.definition_id].properties.get("public")
            for a in e.actors.values()
        )
        if recipe["station"] != "tools" and not station:
            continue
        stock = e.state["living_world"]["stocks"][place]
        inputs = recipe["materials_by_output"][key]
        if any(stock.get(k, 0) < n for k, n in inputs.items()):
            continue
        for k, n in inputs.items():
            stock[k] -= n
        tool["durability"] -= 1
        quantity = content.row(key).get("batch", 1)
        made = e.add_item(key, quantity, owner=id, made_by=id)
        emit(
            e,
            "workshop_product",
            place,
            actor=id,
            resource=key,
            quantity=quantity,
            inputs=inputs,
            item=made["id"],
            cause=e.state["living_world"]["society"]["last"].get(place),
        )
        break


def unit_value(e, item, fallback=0):
    row = content.row(item["template"]) if item and item.get("template") in content.load() else {}
    base = row.get("price_cp", item.get("price_cp", fallback) if item else fallback)
    if item and row.get("kind") in ("weapon", "armour", "household"):
        base = (
            base
            * item.get("quality", 1)
            * max(1, item["durability"])
            // max(1, item["durability_cap"])
        )
    return max(1, base)


def price_percent(e, template=None):
    w = e.state["living_world"]
    local = w["society"]["places"][e.scene.current]
    row = content.load().get(template, {})
    material = row.get("material", template if row.get("kind") == "material" else None)
    if material:
        key = "_".join(material.split("_")[:2]) + "_0"
        scarcity = max(0, 6 - w["stocks"][e.scene.current].get(key, 0)) * 7
    else:
        scarcity = 0
    return min(200, max(local["price"], 100 + scarcity))


def shipments(e, day):
    w = e.state["living_world"]
    s = w["society"]
    for cargo in list(s["cargo"]):
        if cargo["arrival_day"] > day:
            continue
        path = route(e, cargo["source"], cargo["destination"])
        place = cargo["destination"]
        if path is None:
            if not cargo.get("delayed"):
                cargo["delayed"] = emit(
                    e, "shipment_delayed", place, cause=cargo["cause"], shipment=cargo["id"]
                )
            continue
        stock = w["stocks"][place]
        before = stock[cargo["resource"]]
        stock[cargo["resource"]] += cargo["quantity"]
        emit(
            e,
            "shipment_arrived",
            place,
            shipment=cargo["id"],
            resource=cargo["resource"],
            quantity=cargo["quantity"],
            before=before,
            after=stock[cargo["resource"]],
            cause=cargo.get("delayed") or cargo["cause"],
        )
        s["cargo"].remove(cargo)
    for place, stock in sorted(w["stocks"].items()):
        for resource in ("food", "mat_0_0", "mat_2_0"):
            if stock[resource] >= 4 or any(
                c["destination"] == place and c["resource"] == resource for c in s["cargo"]
            ):
                continue
            sources = [
                p
                for p in neighbors(e, place)
                if w["stocks"][p][resource] >= 12 and route(e, p, place) is not None
            ]
            if not sources:
                continue
            source = sorted(sources)[0]
            amount = 4
            w["stocks"][source][resource] -= amount
            cause = emit(
                e,
                "shipment_dispatched",
                source,
                destination=place,
                resource=resource,
                quantity=amount,
                stock_after=w["stocks"][source][resource],
                cause=s["last"].get(source),
            )
            s["cargo"].append(
                {
                    "id": cause,
                    "cause": cause,
                    "source": source,
                    "destination": place,
                    "resource": resource,
                    "quantity": amount,
                    "arrival_day": day + 2,
                }
            )


def ecology(e, place, day):
    w = e.state["living_world"]
    s = w["society"]
    local = s["places"][place]
    nodes = w["nodes"][place]
    weather = w["weather"]
    water_before = local["water"]
    local["water"] = min(
        20,
        max(
            0,
            local["water"]
            + (
                4
                if weather in ("rain", "storm", "flood", "thaw")
                else -2
                if weather == "drought"
                else -1
            ),
        ),
    )
    if local["water"] and local["soil"] and nodes["mat_2_0"] < local["plants_cap"]:
        local["water"] -= 1
        local["soil"] -= 1
        grown = min(
            4 if weather in ("rain", "storm", "flood") else 2,
            local["plants_cap"] - nodes["mat_2_0"],
        )
        nodes["mat_2_0"] += grown
        emit(
            e,
            "plant_growth",
            place,
            resource="mat_2_0",
            quantity=grown,
            water_before=water_before,
            water_after=local["water"],
            soil_after=local["soil"],
            cause=local["weather_cause"],
        )
    if day % 7 == 0 and w["stocks"][place]["food"] > 8:
        w["stocks"][place]["food"] -= 1
        local["soil"] = min(60, local["soil"] + 8)
        emit(
            e,
            "compost_applied",
            place,
            food_consumed=1,
            soil_after=local["soil"],
            cause=s["last"].get(place),
        )
    need = (local["herbivores"] + 3) // 4
    fed = min(need, nodes["mat_2_0"])
    nodes["mat_2_0"] -= fed
    local["prey_hunger"] = 0 if fed == need else local["prey_hunger"] + 1
    local["animal_energy"] = min(30, local["animal_energy"] + fed)
    if local["prey_hunger"] >= 7 and local["herbivores"]:
        local["herbivores"] -= 1
        local["prey_hunger"] = 0
        emit(e, "wildlife_starved", place, quantity=1, cause=s["last"].get(place))
    if day % 3 == 0 and local["predators"]:
        killed = min(local["herbivores"], local["predators"])
        local["herbivores"] -= killed
        local["predator_hunger"] = 0 if killed else local["predator_hunger"] + 3
        if killed:
            emit(e, "predation", place, quantity=killed, cause=s["last"].get(place))
        if local["predator_hunger"] >= 9:
            local["predators"] -= 1
            local["predator_hunger"] = 0
            emit(e, "predator_starved", place, quantity=1, cause=s["last"].get(place))
    if (
        day % 30 == 0
        and local["herbivores"] >= 2
        and fed == need
        and local["animal_energy"] >= 4
        and local["herbivores"] < 12
    ):
        local["animal_energy"] -= 4
        local["herbivores"] += 1
        emit(e, "wildlife_birth", place, quantity=1, cause=s["last"].get(place))
    if (
        day % 60 == 0
        and local["predators"] >= 2
        and local["herbivores"] >= 4
        and local["animal_energy"] >= 6
    ):
        local["animal_energy"] -= 6
        local["predators"] += 1
        emit(e, "predator_birth", place, quantity=1, cause=s["last"].get(place))


def demographics(e, day):
    w = e.state["living_world"]
    s = w["society"]
    for id, person in list(s["people"].items()):
        if id not in e.refs or not person["civilian"]:
            continue
        delta = day - person["last_day"]
        person["last_day"] = day
        person["age_days"] += delta
        if not person["mature"] and person["age_days"] >= 18 * 365:
            person["mature"] = True
            w["residents"][id]["job"] = "resident"
            emit(
                e,
                "resident_adult",
                e.refs[id].place,
                actor=id,
                cause=s["last"].get(e.refs[id].place),
            )
        if (
            w["residents"][id]["hunger"] >= 10
            and e.hp(id) == 0
            and (e.actors[id].state or {}).get("life") != "dead"
        ):
            a = e.actors[id]
            e.actors[id] = replace(a, state=(a.state or {}) | {"life": "dead"})
            emit(
                e,
                "resident_died",
                e.refs[id].place,
                actor=id,
                reason="starvation",
                cause=s["last"].get(e.refs[id].place),
            )
    if day % 90 or len(e.refs) >= 180:
        return
    for place, stock in sorted(w["stocks"].items()):
        adults = [
            id
            for id, p in s["people"].items()
            if p["mature"]
            and p["civilian"]
            and id in e.refs
            and e.refs[id].place == place
            and e.hp(id) > 0
        ]
        children = [
            id
            for id, p in s["people"].items()
            if not p["mature"]
            and p["civilian"]
            and id in e.refs
            and e.refs[id].place == place
            and e.hp(id) > 0
        ]
        if len(adults) < 2 or len(children) >= 4 or stock["food"] < 16:
            continue
        if len(adults) + len(children) >= s["places"][place]["population_cap"]:
            continue
        stock["food"] -= 2
        id = e.mint("resident_child")
        definition = "society_child"
        e.definitions.setdefault(
            definition,
            Definition(
                definition,
                "Ребёнок поселения",
                "actor",
                ("npcs",),
                {"hp_max": 6, "class": "dependent", "age": 0},
                origin="project-homebrew",
            ),
        )
        e.actors[id] = Entity(id, definition, place, state={"hp": 6, "gold_cp": 0})
        e.refs[id] = ActorRef(id, "Ребёнок поселения", place)
        w["residents"][id] = {
            "food": 0,
            "hunger": 0,
            "fatigue": 0,
            "goal": "family",
            "knowledge": [],
            "home": place,
            "work": place,
            "job": "dependent",
        }
        s["people"][id] = {
            "age_days": 0,
            "civilian": True,
            "parents": adults[:2],
            "born_day": day,
            "last_day": day,
            "known_places": {place: {"food": stock["food"], "seen_day": day}},
            "destination": None,
            "route": [],
            "mature": False,
        }
        emit(e, "resident_born", place, actor=id, food_consumed=2, cause=s["last"].get(place))


def day(e, number):
    from rpg_vkr.domain.contracts import expire

    expire(e)
    w = e.state["living_world"]
    s = initialize(e)
    w["day"] = number
    # Weather changes create an explicit upstream record before growth, roads and trade.
    if number % 7 == 1:
        options = ("clear", "rain", "rain", "drought", "fog", "storm", "thaw")
        w["weather"] = options[(number // 7 + e.roll("1d20", "Погода поселений")) % len(options)]
        for place, local in s["places"].items():
            local["weather_cause"] = emit(e, "climate_changed", place, weather=w["weather"])
            if w["weather"] == "storm":
                w.setdefault("blocked_until", {})[place] = e.state["minute"] + 1440
    shipments(e, number)
    group = ("economic", "political", "social", "military", "natural")[number % 5]
    candidates = content.available("event", category=group)
    row = candidates[(number + e.roll("1d100", "Событие поселений")) % len(candidates)]
    if (
        row["season"] == (number // 90) % 4
        and number - w["last_events"].get(row["id"], -999) >= row["cooldown_days"]
    ):
        locations = sorted(w["stocks"])
        if apply_event(e, row, locations[row["role"] % len(locations)]):
            w["last_events"][row["id"]] = number
    legacy.faction_day(e, number)
    engaged = set((e.state.get("battle") or {}).get("order", []))
    for place in sorted(w["stocks"]):
        ecology(e, place, number)
    for id, resident in sorted(w["residents"].items()):
        if id not in e.refs or id in engaged or (e.actors[id].state or {}).get("life") == "dead":
            continue
        if not s["people"][id]["civilian"]:
            continue
        place = e.refs[id].place
        stock = w["stocks"][place]
        if resident["job"] != "dependent" and e.hp(id) > 0:
            livelihood(e, id, place)
        if resident["food"]:
            resident["food"] -= 1
            resident["hunger"] = 0
        elif stock["food"]:
            stock["food"] -= 1
            resident["hunger"] = 0
        else:
            resident["hunger"] += 1
        resident["fatigue"] = min(10, resident["hunger"])
        resident["goal"] = "seek_food" if resident["hunger"] else resident["job"]
        if resident["hunger"] >= 7:
            e.change_hp(id, -1)
    demographics(e, number)
    for place, local in s["places"].items():
        before = local["price"]
        food = w["stocks"][place]["food"]
        blocked = w.get("blocked_until", {}).get(place, 0) > e.state["minute"]
        local["price"] = min(180, 100 + max(0, 12 - food) * 4 + 20 * int(blocked))
        if before != local["price"]:
            emit(
                e,
                "market_repriced",
                place,
                before=before,
                after=local["price"],
                cause=s["last"].get(place),
            )
    w["price_percent"] = s["places"][e.scene.current]["price"]


def advance(e, start, end):
    from rpg_vkr.domain.contracts import expire

    initialize(e)
    expire(e)
    if start // 60 != end // 60:
        hourly(e)
    for number in range(e.state["living_world"]["day"] + 1, end // 1440 + 1):
        day(e, number)


def apply_event(e, row, place=None):
    from rpg_vkr.domain.catalog_world import apply_legacy_event

    s = initialize(e)
    place = place or e.scene.current
    if row["op"] in ("gossip", "exchange_news"):
        people = [
            id
            for id in sorted(e.refs)
            if e.refs[id].place == place
            and e.hp(id) > 0
            and (
                s["people"][id]["civilian"]
                or e.definitions[e.actors[id].definition_id].properties.get("can_speak") is True
            )
        ]
        if len(people) < 2:
            return False
        reporter = people[row["role"] % len(people)]
        recipient = people[(row["role"] + 1) % len(people)]
        resident = e.state["living_world"]["residents"][reporter]
        available = [
            r
            for r in s["ledger"]
            if r["id"] in resident["knowledge"]
            and r.get("resource") == row["resource"]
            and r["kind"] != "rumor_received"
            and r["id"] not in e.state["living_world"]["residents"][recipient]["knowledge"]
        ]
        if not available:
            return False
        fact = available[-1]
        heard = e.state["living_world"]["residents"][recipient].setdefault("rumors", [])
        if any(r["event_id"] == fact["id"] and r["reporter"] == reporter for r in heard):
            return False
        heard.append(
            {
                "event_id": fact["id"],
                "reporter": reporter,
                "confirmed": False,
                "topic": row["resource"],
                "received_minute": e.state["minute"],
            }
        )
        heard[:] = heard[-30:]
        emit(
            e,
            "rumor_received",
            place,
            actor=recipient,
            reporter=reporter,
            reported_event=fact["id"],
            confirmed=False,
            resource=row["resource"],
            template=row["id"],
            cause=fact["id"],
        )
        return True
    if row["op"] in ("delivery", "resupply", "subsidy"):
        resource, amount = row["resource"], row["amount"]
        sources = [
            p
            for p in neighbors(e, place)
            if e.state["living_world"]["stocks"][p].get(resource, 0) >= amount
        ]
        if not sources:
            return False
        source = sources[row["role"] % len(sources)]
        e.state["living_world"]["stocks"][source][resource] -= amount
        cause = emit(
            e,
            "shipment_dispatched",
            source,
            destination=place,
            resource=resource,
            quantity=amount,
            template=row["id"],
            cause=s["last"].get(source),
        )
        s["cargo"].append(
            {
                "id": cause,
                "cause": cause,
                "source": source,
                "destination": place,
                "resource": resource,
                "quantity": amount,
                "arrival_day": e.state["living_world"]["day"] + 2,
            }
        )
        return True
    if row["op"] in ("caravan", "rotation", "relocate", "withdraw"):
        people = [id for id in sorted(e.refs) if e.refs[id].place == place and e.hp(id) > 0]
        destinations = neighbors(e, place)
        if not people or not destinations:
            return False
        id = people[row["role"] % len(people)]
        destination = destinations[row["role"] % len(destinations)]
        steps = route(e, place, destination)
        if not steps:
            return False
        legacy.move_actor(e, id, steps[0])
        emit(
            e,
            "resident_journey",
            place,
            actor=id,
            destination=steps[0],
            template=row["id"],
            cause=s["last"].get(place),
        )
        return True
    changed = apply_legacy_event(e, row, place)
    if changed:
        if row["op"] == "demand":
            s["places"][place]["price"] = e.state["living_world"]["price_percent"]
        cause = emit(
            e,
            "regional_event",
            place,
            template=row["id"],
            resource=row["resource"],
            operation=row["op"],
            cause=s["last"].get(place),
        )
        if row["category"] == "natural":
            s["places"][place]["weather_cause"] = cause
    return changed


def explore(e):
    from rpg_vkr.domain.catalog_actions_v2 import level

    w = e.state["living_world"]
    s = initialize(e)
    place = e.scene.current
    local = s["places"][place]
    key = f"{place}:{w['day']}"
    if key in w["exploration"]:
        raise ValueError("Этот участок сегодня уже исследован.")
    w["exploration"][key] = True
    pool = []
    for r in content.available("creature", level(e) + 1):
        if r["habitat"] != local["habitat"] or "defeat:" + r["id"] in e.state["achievements"]:
            continue
        if r["category"] == "beast":
            field = "predators" if r["ecological_role"] == "predator" else "herbivores"
            if local[field] > 0 and local["animal_energy"] >= r["spawn_cost"]:
                pool.append(r)
        elif w["nodes"][place]["mat_9_0"] >= r["spawn_cost"]:
            pool.append(r)
    if not pool:
        e.text.append("Новых следов нет.")
        return
    row = pool[(e.roll("1d100", "Встреча") - 1) % len(pool)]
    if row["category"] == "beast":
        field = "predators" if row["ecological_role"] == "predator" else "herbivores"
        local[field] -= 1
        local["animal_energy"] -= row["spawn_cost"]
    else:
        w["nodes"][place]["mat_9_0"] -= row["spawn_cost"]
    id = legacy.spawn_creature(e, row, key)
    emit(
        e,
        "wildlife_contact",
        place,
        actor=id,
        resource=row["id"],
        quantity=1,
        cause=s["last"].get(place),
    )
    return id
