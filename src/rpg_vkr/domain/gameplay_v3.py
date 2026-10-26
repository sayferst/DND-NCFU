"""Third playable revision: declared factions, autonomous projects and NPC information."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain import gameplay_v2 as v2
from rpg_vkr.domain.catalog import Catalog
from rpg_vkr.domain.factions import VERSION as WORLD_VERSION
from rpg_vkr.domain.factions import contact, initialize, simulate, tax_recipient
from rpg_vkr.domain.interactions import InteractiveWorld
from rpg_vkr.domain.resources import reconcile
from rpg_vkr.domain.world import WorldState

VERSION = "gameplay-v3-playable-3"
CATALOG_VERSION = "gameplay-catalog-3"


def initial(identity, character):
    state = v2.initial(identity, character)
    state.update(
        version=VERSION,
        catalog_version=CATALOG_VERSION,
        world_simulation_version=WORLD_VERSION,
        factions_v3={},
        known_factions={},
        simulation_seq=0,
    )
    return state


def execute(state, command, args, context, dice):
    if (
        state.get("version") != VERSION
        or state.get("catalog_version") != CATALOG_VERSION
        or state.get("world_simulation_version") != WORLD_VERSION
    ):
        raise ValueError("Неизвестная версия симуляции мира.")
    catalog = Catalog.from_dict(context["catalog"]) if context["catalog"] else None
    scene = InteractiveWorld.from_dict(context["scene"])
    state = initialize(state, catalog, scene)
    old_context = context
    donation = None
    if command == "donate":
        if not isinstance(args, dict) or set(args) != {"faction", "amount_cp"}:
            raise ValueError("Неверные параметры взноса.")
        world = WorldState.from_dict(context["world"])
        if world.hp <= 0 or state["active"]:
            raise ValueError("Взнос недоступен во время боя или после выбытия.")
        amount = args["amount_cp"]
        if type(amount) is not int or not 1 <= amount <= 1_000_000:
            raise ValueError("Взнос должен быть положительным целым числом медных.")
        if not isinstance(args["faction"], str):
            raise ValueError("Выберите известную фракцию.")
        faction = contact(state, catalog, scene, args["faction"])
        coins = world.gold * 100 + state["copper"]
        if coins < amount:
            raise ValueError("Не хватает монет на взнос.")
        after_world = replace(world, gold=(coins - amount) // 100)
        state["copper"] = (coins - amount) % 100
        faction["treasury_cp"] += amount
        faction["reputation"] = min(100, faction["reputation"] + amount // 100)
        scene = reconcile(scene, world, after_world, context["turn"], catalog)
        donation = {"kind": "donation", "faction": faction["id"], "amount_cp": amount}
        context = context | {"world": asdict(after_world), "scene": scene.to_dict()}
    translated = deepcopy(state)
    translated.update(version=v2.VERSION, catalog_version=v2.CATALOG_VERSION)
    result = v2.execute(
        translated,
        "wait" if donation else command,
        {"minutes": 5} if donation else args,
        context,
        dice,
    )
    # Revision one had an unnamed universal artisan counter. Revision three
    # advances only groups actually declared in this world's catalog.
    result["text"] = "\n".join(
        line for line in result["text"].splitlines() if not line.startswith("Ремесленная община:")
    )
    state = result["state"]
    state.pop("faction_projects", None)
    state.update(version=VERSION, catalog_version=CATALOG_VERSION)
    world = WorldState.from_dict(result["world"])
    scene = InteractiveWorld.from_dict(result["scene"])
    catalog = Catalog.from_dict(result["catalog"]) if result["catalog"] else None
    events = []
    if donation:
        events.append(donation)
        result["text"] = (
            f"Передано {donation['amount_cp']} медных объединению "
            f"{state['factions_v3'][donation['faction']]['name']}.\n" + result["text"]
        )
    receipt = result.get("transaction")
    authority = tax_recipient(state)
    if receipt and receipt["operation"] == "buy" and authority:
        fee = (receipt["price_cp"] * 5 + 99) // 100
        coins = world.gold * 100 + state["copper"]
        if coins < fee:
            raise ValueError("Не хватает монет на объявленную пошлину5%.")
        after_world = replace(world, gold=(coins - fee) // 100)
        state["copper"] = (coins - fee) % 100
        scene = reconcile(scene, world, after_world, old_context["turn"], catalog)
        world = after_world
        authority["treasury_cp"] += fee
        receipt.update(
            base_price_cp=receipt["price_cp"],
            duty_cp=fee,
            duty_faction=authority["id"],
            price_cp=receipt["price_cp"] + fee,
        )
        events.append({"kind": "market_duty", "faction": authority["id"], "amount_cp": fee})
        state["known_factions"][authority["id"]] = {
            "id": authority["id"],
            "name": authority["name"],
            "goal": authority["goal"],
            "reputation": authority["reputation"],
            "last_seen_minute": state["minute"],
            "news": "Объявлена пошлина на покупки5%.",
        }
        result["text"] += f"\nПошлина {fee} медных в пользу {authority['name']}."
    state, scene, autonomous = simulate(state, catalog, scene)
    events.extend(autonomous)
    result.update(state=state, world=asdict(world), scene=scene.to_dict(), simulation_events=events)
    return result
