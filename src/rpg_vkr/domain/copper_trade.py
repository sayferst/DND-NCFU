"""Exact copper transactions for physical scene stacks; legacy transact stays frozen."""

from dataclasses import replace

from rpg_vkr.domain.catalog import validate_plan_properties
from rpg_vkr.domain.interactions import Step, WorldPlan, apply_plan
from rpg_vkr.domain.resources import activate, project, properties, reconcile, type_mapping
from rpg_vkr.domain.trade import merchant


def source_entity(catalog, item_id, aliases):
    seen = set()
    while item_id not in seen:
        seen.add(item_id)
        entity = next((e for e in catalog.entities if e.id == item_id), None)
        if entity:
            return entity
        item_id = aliases.get(item_id)
        if item_id is None:
            return None
    raise ValueError("Цикл происхождения физического экземпляра.")


def condition_price(definition, entity, quantity):
    maximum = definition.properties.get("durability", 20)
    current = (entity.state or {}).get("condition", maximum) if entity else maximum
    if (
        type(maximum) is not int
        or maximum < 1
        or type(current) is not int
        or not 0 <= current <= maximum
    ):
        raise ValueError("Неверная прочность физического предмета.")
    return definition.price_cp * quantity * current // maximum


def transact_copper(
    catalog,
    scene,
    world,
    copper,
    merchant_id,
    item_id,
    operation,
    quantity,
    turn_index,
    aliases,
    coefficient=100,
):
    if operation not in {"buy", "sell"} or type(quantity) is not int or not 1 <= quantity <= 1000:
        raise ValueError("Неверная сделка или количество.")
    if type(copper) is not int or not 0 <= copper < 100:
        raise ValueError("Неверный остаток медных монет.")
    if type(coefficient) is not int or not 100 <= coefficient <= 120:
        raise ValueError("Неверный рыночный коэффициент.")
    owner = merchant(catalog, merchant_id)
    if not any(a.id == merchant_id and a.place == scene.current for a in scene.actor_refs):
        raise ValueError("Торговца нет рядом.")
    scene = activate(scene, world, catalog, aliases)
    item = next((t for t in scene.things if t.id == item_id), None)
    if not item or quantity > item.quantity or item.resource == "gold":
        raise ValueError("Товар отсутствует в указанном количестве.")
    if scene.root_holder(item) != (merchant_id if operation == "buy" else "hero"):
        raise ValueError("Товар не находится у продавца.")
    if operation == "sell" and item.owner not in {"", "hero"}:
        raise ValueError("Торговец не покупает чужую собственность.")
    if item.container and any(t.holder == item.id for t in scene.things):
        raise ValueError("Сначала освободите контейнер.")
    mapping = type_mapping(catalog, aliases)
    type_id = "type_bandage" if item.resource == "bandages" else mapping.get(item.id)
    definition = next((d for d in catalog.definitions if d.id == type_id), None)
    if not definition or definition.price_cp is None or definition.price_cp < 1:
        raise ValueError("Для предмета нет цены.")
    base = condition_price(definition, source_entity(catalog, item.id, aliases), quantity)
    price = (base * coefficient + 99) // 100 if operation == "buy" else base // 2
    if price < 1:
        raise ValueError("Продайте более крупную партию: цена ниже медной монеты.")
    wallet = (owner.state or {}).get("gold_cp", 0)
    if type(wallet) is not int or wallet < 0:
        raise ValueError("Неверное состояние кошелька торговца.")
    coins, by_id = [], {t.id: t for t in scene.things}
    for coin in scene.things:
        if coin.resource != "gold" or scene.root_holder(coin) != merchant_id:
            continue
        cursor, blocked = coin, False
        while cursor.holder in by_id:
            cursor = by_id[cursor.holder]
            if properties(scene, cursor.id, catalog).get("locked"):
                blocked = True
        if not blocked:
            coins.append(coin)
    available = project(scene, world)
    hero_coins = available.gold * 100 + copper
    merchant_coins = wallet + sum(t.quantity * 100 for t in coins)
    if operation == "buy" and hero_coins < price or operation == "sell" and merchant_coins < price:
        raise ValueError("Для сделки не хватает денег.")
    plan = WorldPlan(
        (
            Step(
                "take" if operation == "buy" else "give",
                item_id,
                quantity,
                "" if operation == "buy" else merchant_id,
            ),
        )
    )
    validate_plan_properties(catalog, scene, plan, turn_index=turn_index, aliases=aliases)
    moved, _, _, _ = apply_plan(scene, plan, turn_index=turn_index)
    moved_id = item_id if quantity == item.quantity else f"split_{turn_index}_0"
    moved = replace(
        moved,
        things=tuple(
            replace(t, owner="hero" if operation == "buy" else merchant_id)
            if t.id == moved_id
            else t
            for t in moved.things
        ),
    )
    delta = -price if operation == "buy" else price
    total = hero_coins + delta
    projected = project(moved, world)
    after = replace(projected, gold=total // 100)
    moved = reconcile(moved, projected, after, turn_index, catalog)
    balance = wallet - delta
    if balance < 0:
        needed = (-balance + 99) // 100
        remaining = needed
        things = list(moved.things)
        for coin in coins:
            amount = min(remaining, coin.quantity)
            things.remove(coin)
            if amount < coin.quantity:
                things.append(replace(coin, quantity=coin.quantity - amount))
            remaining -= amount
            if not remaining:
                break
        moved = replace(moved, things=tuple(things))
        balance += needed * 100
    changed = replace(owner, state=(owner.state or {}) | {"gold_cp": balance})
    catalog = replace(
        catalog, entities=tuple(changed if e.id == owner.id else e for e in catalog.entities)
    )
    receipt = {
        "operation": operation,
        "merchant": merchant_id,
        "item": item_id,
        "moved_id": moved_id,
        "quantity": quantity,
        "price_cp": price,
        "name": item.name,
    }
    return catalog, moved, after, total % 100, receipt
