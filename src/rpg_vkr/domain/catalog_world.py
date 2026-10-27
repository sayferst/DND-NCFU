"""Finite stocks, conserved money, schedules and executable world-event policies."""

from dataclasses import replace

from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.interactions import ActorRef


def initialize(e):
    w = e.state.get("living_world")
    if not w or w.get("version") != "canonical-world-2":
        w = {
            "version": "canonical-world-2",
            "day": e.state["minute"] // 1440,
            "nodes": {},
            "stocks": {},
            "residents": {},
            "relations": {},
            "territories": {},
            "observed": {},
            "sequence": 0,
            "reserve": {f"mat_{m}_0": 10000 for m in range(10)},
            "treasury_cp": 5000,
            "price_percent": 100,
            "weather": "clear",
            "last_events": {},
            "exploration": {},
        }
        e.state["living_world"] = w
    for place in e.scene.places:
        w["nodes"].setdefault(place.id, {f"mat_{m}_0": 30 for m in range(10)})
        w["stocks"].setdefault(place.id, {**{f"mat_{m}_0": 10 for m in range(10)}, "food": 30})
    for id, ref in e.refs.items():
        if id not in e.actors:
            continue
        entity = e.actors[id]
        definition = e.definitions[entity.definition_id]
        if definition.kind != "actor":
            continue
        w["residents"].setdefault(
            id,
            {
                "food": 3,
                "hunger": 0,
                "fatigue": 0,
                "goal": "work",
                "knowledge": [],
                "home": ref.place,
                "work": definition.properties.get("workplace", ref.place),
                "job": definition.properties.get("class", "resident"),
            },
        )
        seeded = w.setdefault("seeded_merchants", [])
        if id not in seeded and definition.properties.get("class") in (
            "merchant",
            "trader",
            "shopkeeper",
        ):
            stock = w["stocks"][ref.place]
            for m in range(10):
                template = f"mat_{m}_0"
                if stock[template] >= 2:
                    stock[template] -= 2
                    e.add_item(template, 2, owner=id)
            if stock["mat_0_0"] >= 2:
                stock["mat_0_0"] -= 2
                e.add_item("house_0_0", owner=id)
            if stock["mat_2_0"] >= 2:
                stock["mat_2_0"] -= 2
                e.add_item("use_potions_3_0", owner=id)
            if stock["mat_1_0"] >= 2:
                stock["mat_1_0"] -= 2
                e.add_item("use_ammunition_0_0", quantity=6, owner=id)
            seeded.append(id)
    for faction_id, faction in e.state.get("factions_v3", {}).items():
        here = [
            m
            for m in faction["members"]
            if m in e.refs and e.refs[m].place == e.scene.current and e.hp(m) > 0
        ]
        if here:
            e.state["known_factions"][faction_id] = {
                "id": faction_id,
                "name": faction["name"],
                "goal": faction["goal"],
                "reputation": faction["reputation"],
                "last_seen_minute": e.state["minute"],
                "news": faction["last_public"],
            }
    return w


def faction_day(e, day):
    """Finite projects transfer funds to workers; no creation of coins or materials."""
    w = e.state["living_world"]
    for id, faction in sorted(e.state.get("factions_v3", {}).items()):
        if faction["last_day"] >= day:
            continue
        faction["last_day"] = day
        members = [
            m
            for m in faction["members"]
            if m in e.refs
            and e.hp(m) > 0
            and m not in (e.state.get("battle") or {}).get("order", [])
        ]
        if not members or faction["treasury_cp"] < 100:
            continue
        member = members[day % len(members)]
        place = e.refs[member].place
        stock = w["stocks"][place]
        resource = "mat_0_0" if faction["goal"] == "security" else "mat_1_0"
        if stock.get(resource, 0) < 2:
            continue
        stock[resource] -= 2
        faction["treasury_cp"] -= 100
        faction["spent_cp"] += 100
        _wallet(e, member, 100)
        faction["influence"] = min(100, faction["influence"] + 1)
        if faction["goal"] == "security":
            actor = e.actors[member]
            e.actors[member] = replace(actor, state=(actor.state or {}) | {"fortification": 2})
            w["residents"][member]["job"] = "guard"
            faction["last_public"] = "Объединение оплатило патруль и укрепления."
        else:
            stock["food"] += 4
            faction["last_public"] = "Объединение оплатило производство припасов."
        event = {
            "kind": "faction_project",
            "faction": id,
            "actor": member,
            "place": place,
            "minute": day * 1440,
            "spent_cp": 100,
        }
        e.state["world_log"].append(event)
        w["observed"].setdefault(place, []).append(event)
        if place == e.scene.current:
            e.events.append(event)


def move_actor(e, id, place):
    if place not in {p.id for p in e.scene.places}:
        return False
    if id not in e.refs or e.refs[id].place == place:
        return False
    e.refs[id] = replace(e.refs[id], place=place)
    e.actors[id] = replace(e.actors[id], parent_id=place)
    return True


def _wallet(e, id, delta):
    entity = e.actors[id]
    state = dict(entity.state or {})
    before = state.get("gold_cp", 0)
    if before + delta < 0:
        return False
    state["gold_cp"] = before + delta
    e.actors[id] = replace(entity, state=state)
    return True


def apply_event(e, row, place=None):
    w = initialize(e)
    place = place or e.scene.current
    if place not in w["nodes"]:
        return False
    actors = [
        id
        for id, r in sorted(e.refs.items())
        if r.place == place
        and id in e.actors
        and e.hp(id) > 0
        and id not in (e.state.get("battle") or {}).get("order", [])
    ]
    if not actors:
        return False
    id = actors[row["role"] % len(actors)]
    other = actors[(row["role"] + 1) % len(actors)]
    resource, amount, money = row["resource"], row["amount"], row["money"]
    node, stock = w["nodes"][place], w["stocks"][place]
    op = row["op"]
    changed = False
    if op in ("delivery", "resupply", "subsidy"):
        if w["reserve"].get(resource, 0) >= amount:
            w["reserve"][resource] -= amount
            stock[resource] = stock.get(resource, 0) + amount
            changed = True
    elif op == "production":
        if stock.get(resource, 0) >= amount:
            stock[resource] -= amount
            stock["food"] += amount * 2
            changed = True
    elif op in ("wage", "aid", "commission"):
        if w["treasury_cp"] >= money:
            w["treasury_cp"] -= money
            _wallet(e, id, money)
            changed = True
    elif op in ("levy", "fortify", "recruit"):
        if _wallet(e, id, -money):
            w["treasury_cp"] += money
            changed = True
        if changed and op == "fortify":
            entity = e.actors[id]
            e.actors[id] = replace(entity, state=(entity.state or {}) | {"fortification": amount})
        if changed and op == "recruit":
            w["residents"][id]["job"] = "guard"
    elif op == "demand":
        before = w["price_percent"]
        w["price_percent"] = min(180, 80 + row["threshold"] * 20 + amount)
        changed = w["price_percent"] != before
    elif op in ("caravan", "rotation", "relocate", "withdraw"):
        destinations = sorted(p.id for p in e.scene.places if p.id != place)
        if destinations:
            changed = move_actor(e, id, destinations[row["role"] % len(destinations)])
    elif op in ("maintenance", "assist", "rescue"):
        if stock.get(resource, 0) >= amount and e.hp(id) < e.actor(id)[1].properties["hp_max"]:
            stock[resource] -= amount
            e.change_hp(id, amount)
            changed = True
    elif op in ("closure", "embargo"):
        entity = e.actors[id]
        e.actors[id] = replace(
            entity,
            state=(entity.state or {}) | {"closed_until": e.state["minute"] + row["duration"]},
        )
        changed = True
    elif op in ("treaty", "truce", "cooperate"):
        key = ":".join(sorted((id, other)))
        before = w["relations"].get(key, 0)
        w["relations"][key] = min(100, before + amount)
        changed = w["relations"][key] != before
    elif op == "territory":
        if w["treasury_cp"] >= money:
            # A territorial claim reserves real funds; they enter the guard's wallet.
            w["treasury_cp"] -= money
            _wallet(e, id, money)
            w["territories"][place] = {"actor": id, "resource": resource, "day": w["day"]}
            changed = True
    elif op in ("office", "apprentice"):
        resident = w["residents"][id]
        new_job = ("artisan", "guard", "merchant", "farmer")[row["threshold"] - 1]
        changed = resident["job"] != new_job
        resident["job"] = new_job
    elif op == "share_food":
        if stock["food"] >= amount:
            stock["food"] -= amount
            w["residents"][id]["food"] += amount
            changed = True
    elif op == "exchange_news":
        shared = [
            v
            for v in w["residents"][id]["knowledge"]
            if v not in w["residents"][other]["knowledge"]
        ]
        if shared:
            w["residents"][other]["knowledge"].extend(shared[:amount])
            changed = True
    elif op in ("dispute", "raid"):
        key = ":".join(sorted((id, other)))
        w["relations"][key] = max(-100, w["relations"].get(key, 0) - amount)
        if op == "raid" and id != other:
            e.damage(other, e.roll("1d4", "Стычка NPC"), "physical", id)
        changed = True
    elif op == "celebrate":
        if _wallet(e, id, -money):
            _wallet(e, other, money)
            w["residents"][id]["fatigue"] = 0
            changed = True
    elif op == "patrol":
        entity = e.actors[id]
        before = (entity.state or {}).get("patrol_strength", 0)
        e.actors[id] = replace(
            entity, state=(entity.state or {}) | {"patrol_strength": amount + row["threshold"]}
        )
        changed = before != amount + row["threshold"]
    elif op in ("rain", "drought", "fog", "storm", "frost", "flood", "thaw"):
        w["weather"] = op
        w["weather_until"] = e.state["minute"] + row["duration"]
        w.setdefault("environment", {})[resource] = {
            "kind": op,
            "amount": amount,
            "until": w["weather_until"],
        }
        if op in ("drought", "frost"):
            loss = min(node.get(resource, 0), amount)
            node[resource] = node.get(resource, 0) - loss
            w["reserve"][resource] += loss
        elif op == "storm":
            e.status(id, "slow", amount, 2)
        elif op == "flood":
            w.setdefault("blocked_until", {})[place] = w["weather_until"]
            for item in e.state["items"]:
                if item["owner"] == id:
                    item["durability"] = max(0, item["durability"] - amount)
        changed = True
    elif op == "growth":
        if w["reserve"].get(resource, 0) >= amount:
            w["reserve"][resource] -= amount
            node[resource] = node.get(resource, 0) + amount
            changed = True
    if changed:
        event = {
            "id": row["id"],
            "kind": row["category"],
            "operation": op,
            "resource": resource,
            "place": place,
            "actor": id,
            "minute": e.state["minute"],
        }
        e.state["world_log"].append(event)
        e.state["world_log"] = e.state["world_log"][-200:]
        w["observed"].setdefault(place, []).append(event)
        w["observed"][place] = w["observed"][place][-20:]
        for observer in actors:
            knowledge = w["residents"][observer]["knowledge"]
            knowledge.append(row["id"])
            knowledge[:] = knowledge[-50:]
        if place == e.scene.current:
            e.events.append(event)
    return changed


def advance_world(e, start, end):
    w = initialize(e)
    engaged = set((e.state.get("battle") or {}).get("order", []))
    if end // 60 != start // 60:
        hour = end // 60 % 24
        for id, resident in sorted(w["residents"].items()):
            if id not in e.actors or id in engaged or e.hp(id) <= 0:
                continue
            destination = resident["work"] if 8 <= hour < 18 else resident["home"]
            if move_actor(e, id, destination):
                event = {"kind": "schedule", "actor": id, "place": destination, "minute": end}
                if destination == e.scene.current:
                    e.events.append(event)
    for day in range(w["day"] + 1, end // 1440 + 1):
        w["day"] = day
        faction_day(e, day)
        for node in w["nodes"].values():
            for resource in ("mat_1_0", "mat_2_0"):
                if node[resource] < 30 and w["reserve"][resource] > 0:
                    node[resource] += 1
                    w["reserve"][resource] -= 1
        for id, resident in sorted(w["residents"].items()):
            if id not in e.actors or id in engaged or e.hp(id) <= 0:
                continue
            place = e.refs[id].place
            stock = w["stocks"][place]
            if resident["food"]:
                resident["food"] -= 1
                resident["hunger"] = 0
            elif stock["food"]:
                stock["food"] -= 1
                resident["hunger"] = 0
            elif w["nodes"][place]["mat_2_0"]:
                w["nodes"][place]["mat_2_0"] -= 1
                resident["food"] += 1
                resident["hunger"] = 0
            else:
                resident["hunger"] += 1
            resident["goal"] = "seek_food" if resident["hunger"] else resident["job"]
            resident["fatigue"] = min(10, resident["hunger"])
            if resident["hunger"] >= 7:
                e.change_hp(id, -1)
            if resident["job"] == "farmer" and stock["mat_2_0"] > 0:
                stock["mat_2_0"] -= 1
                stock["food"] += 3
        for group in ("economic", "political", "social", "military", "natural"):
            entries = content.available("event", category=group)
            row = entries[(day * 7 + e.roll("1d20", "Выбор события мира")) % len(entries)]
            if (day // 90) % 4 != row["season"] or day - w["last_events"].get(row["id"], -99) < row[
                "cooldown_days"
            ]:
                continue
            places = sorted(w["nodes"])
            place = places[(day + row["role"]) % len(places)]
            if apply_event(e, row, place):
                w["last_events"][row["id"]] = day
    if w.get("weather_until", 0) <= end:
        w["weather"] = "clear"


def explore(e):
    from rpg_vkr.domain.catalog_actions_v2 import level

    w = initialize(e)
    key = e.scene.current + ":" + str(w["day"])
    if key in w["exploration"]:
        raise ValueError("Этот участок сегодня уже исследован.")
    w["exploration"][key] = True
    creatures = content.available("creature", level(e) + 1)
    choices = [r for r in creatures if "defeat:" + r["id"] not in e.state["achievements"]]
    if not choices:
        e.text.append("Новых следов нет.")
        return
    row = choices[
        (
            (e.roll("1d100", "Встреча: старший разряд") - 1) * 100
            + e.roll("1d100", "Встреча: младший разряд")
            - 1
        )
        % len(choices)
    ]
    return spawn_creature(e, row, key)


def spawn_creature(e, row, key):
    row = content.row(row["id"], "creature")
    id = e.mint("encounter")
    definition_id = "gc_" + row["id"]
    if definition_id not in e.definitions:
        e.definitions[definition_id] = Definition(
            definition_id,
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
            origin="project-homebrew",
        )
    e.actors[id] = Entity(
        id,
        definition_id,
        e.scene.current,
        state={"hp": row["hp"], "st": 20, "mp": 10, "encounter_source": key},
    )
    e.refs[id] = ActorRef(id, row["name"][:80], e.scene.current)
    e.events.append(
        {"kind": "encounter_available", "id": id, "template": row["id"], "place": e.scene.current}
    )
    e.text.append("Обнаружен след: " + row["name"] + ". Можно вступить в контакт или уйти.")
    return id
