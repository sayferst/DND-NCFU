"""Finite causal supply chains and bounded ecological cohorts for catalog revision two."""

from rpg_vkr.domain import catalog_world as world

BIOMES = (
    ("лес", 0),
    ("степ", 1),
    ("гор", 2),
    ("болот", 3),
    ("руин", 4),
    ("пустын", 5),
    ("пещер", 6),
    ("пристан", 7),
    ("берег", 7),
    ("тундр", 8),
)


def initialize(e):
    w = e.state["living_world"]
    if "causal" not in w:
        w["causal"] = {"sequence": 0, "shipments": [], "markets": {}, "ecology": {}, "chains": []}
    c = w["causal"]
    for place in e.scene.places:
        key = place.name.casefold()
        habitat = next((b for word, b in BIOMES if word in key), 9)
        c["ecology"].setdefault(
            place.id,
            {
                "habitat": habitat,
                "herbivores": 8,
                "predators": 2,
                "capacity": 12,
                "encounter_budget": 24,
                "dependent_children": 0,
                "hunger_days": 0,
            },
        )
        c["markets"].setdefault(place.id, 100)
    w["price_percent"] = c["markets"].get(e.scene.current, 100)
    return c


def emit(e, kind, place, *, cause=None, **changes):
    w = e.state["living_world"]
    c = initialize(e)
    c["sequence"] += 1
    event = {
        "id": f"chain_{c['sequence']}",
        "kind": kind,
        "place": place,
        "minute": e.state["minute"],
        "cause": cause,
        **changes,
    }
    c["chains"].append(event)
    c["chains"] = c["chains"][-200:]
    e.state["world_log"].append(event)
    e.state["world_log"] = e.state["world_log"][-200:]
    observed = w["observed"].setdefault(place, [])
    observed.append(event)
    observed[:] = observed[-20:]
    for id, resident in w["residents"].items():
        if id in e.refs and e.refs[id].place == place and e.hp(id) > 0:
            resident["knowledge"].append(event["id"])
            resident["knowledge"][:] = resident["knowledge"][-50:]
    if place == e.scene.current:
        e.events.append(event)
    return event["id"]


def day(e, number, *, previous_food=None):
    w, c = e.state["living_world"], initialize(e)
    for shipment in list(c["shipments"]):
        place = shipment["destination"]
        if shipment["arrival_day"] > number:
            continue
        if w.get("blocked_until", {}).get(place, 0) > e.state["minute"]:
            if not shipment.get("blocked"):
                shipment["blocked"] = emit(
                    e, "shipment_delayed", place, cause=shipment["cause"], shipment=shipment["id"]
                )
            continue
        stock = w["stocks"][place]
        resource, amount = shipment["resource"], shipment["quantity"]
        before = stock.get(resource, 0)
        stock[resource] = before + amount
        emit(
            e,
            "shipment_arrived",
            place,
            cause=shipment.get("blocked") or shipment["cause"],
            resource=resource,
            before=before,
            after=stock[resource],
            shipment=shipment["id"],
        )
        c["shipments"].remove(shipment)
    for place in sorted(w["stocks"]):
        stock, population = w["stocks"][place], c["ecology"][place]
        cause = None
        if previous_food is not None and previous_food[place] != stock["food"]:
            cause = emit(
                e, "daily_food_balance", place, before=previous_food[place], after=stock["food"]
            )
        if w.get("blocked_until", {}).get(place, 0) > e.state["minute"]:
            cause = emit(
                e, "road_closed", place, until=w["blocked_until"][place], weather=w["weather"]
            )
        incoming = any(s["destination"] == place for s in c["shipments"])
        if stock["food"] < 12 and not incoming and w["reserve"].get("mat_2_0", 0) >= 4:
            # Reserve is debited at dispatch; delayed cargo remains in transit.
            w["reserve"]["mat_2_0"] -= 4
            dispatch = emit(
                e, "shipment_dispatched", place, cause=cause, resource="mat_2_0", quantity=4
            )
            c["shipments"].append(
                {
                    "id": dispatch,
                    "cause": dispatch,
                    "destination": place,
                    "resource": "mat_2_0",
                    "quantity": 4,
                    "arrival_day": number + 2,
                }
            )
        workers = [
            id
            for id, r in w["residents"].items()
            if id in e.refs
            and e.refs[id].place == place
            and e.hp(id) > 0
            and r["job"] in ("farmer", "artisan", "merchant", "trader", "shopkeeper")
        ]
        if workers and stock.get("mat_2_0", 0) and stock["food"] < 15:
            before = stock["food"]
            stock["mat_2_0"] -= 1
            stock["food"] += 3
            cause = emit(
                e,
                "food_processed",
                place,
                cause=cause,
                resource="mat_2_0",
                consumed=1,
                food_before=before,
                food_after=stock["food"],
            )
        # Deliver a small, finite part of real local stocks to a physically present merchant.
        for id in workers:
            if w["residents"][id]["job"] not in ("merchant", "trader", "shopkeeper"):
                continue
            resource = "mat_2_0"
            amount = min(1, stock.get(resource, 0))
            if amount:
                stock[resource] -= amount
                item = e.add_item(resource, amount, owner=id)
                emit(
                    e,
                    "merchant_supplied",
                    place,
                    cause=cause,
                    actor=id,
                    item=item["id"],
                    quantity=amount,
                )
        old_price = c["markets"][place]
        price = min(
            180,
            100
            + max(0, 12 - stock["food"]) * 5
            + (20 if cause and w.get("blocked_until", {}).get(place, 0) > e.state["minute"] else 0),
        )
        c["markets"][place] = price
        if price != old_price:
            emit(
                e,
                "market_repriced",
                place,
                cause=cause,
                food_stock=stock["food"],
                before=old_price,
                after=price,
            )
        plants = w["nodes"][place]
        children = population["dependent_children"]
        if children:
            food = min(children, stock["food"])
            stock["food"] -= food
            population["dependant_hunger"] = (
                0 if food == children else population.get("dependant_hunger", 0) + 1
            )
            if population["dependant_hunger"] >= 7:
                population["dependent_children"] -= 1
                population["dependant_hunger"] = 0
                emit(e, "household_loss", place, dependants=population["dependent_children"])
        if population["herbivores"] and plants.get("mat_2_0", 0):
            plants["mat_2_0"] -= 1
            population["hunger_days"] = 0
            if number % 30 == 0 and population["herbivores"] < population["capacity"]:
                population["herbivores"] += 1
                emit(e, "wildlife_birth", place, population=population["herbivores"])
        else:
            population["hunger_days"] += 1
            if population["hunger_days"] >= 7 and population["herbivores"]:
                population["herbivores"] -= 1
                emit(e, "wildlife_loss", place, population=population["herbivores"])
        if number % 14 == 0 and population["predators"] and population["herbivores"]:
            population["herbivores"] -= 1
            emit(e, "predation", place, herbivores=population["herbivores"])
        if (
            number % 90 == 0
            and len(workers) >= 2
            and stock["food"] >= 2
            and population["dependent_children"] < 4
        ):
            stock["food"] -= 2
            population["dependent_children"] += 1
            emit(
                e,
                "household_birth",
                place,
                dependants=population["dependent_children"],
                food_consumed=2,
            )
        for id, resident in sorted(w["residents"].items()):
            if (
                resident["hunger"] < 3
                or id not in e.refs
                or e.refs[id].place != place
                or e.hp(id) <= 0
            ):
                continue
            source = e.scene.place(place)
            neighbors = [p.id for p in e.scene.places if p.parent == place or p.id == source.parent]
            destinations = [
                p
                for p in neighbors
                if w["stocks"][p]["food"] > stock["food"]
                and w.get("blocked_until", {}).get(p, 0) <= e.state["minute"]
            ]
            if destinations and world.move_actor(e, id, sorted(destinations)[0]):
                emit(e, "resident_migrated", place, actor=id, destination=e.refs[id].place)
    w["price_percent"] = c["markets"].get(e.scene.current, 100)


def permit_encounter(e, rows):
    c = initialize(e)
    population = c["ecology"][e.scene.current]
    return [
        r
        for r in rows
        if r["habitat"] == population["habitat"]
        and r["spawn_cost"] <= population["encounter_budget"]
    ]
