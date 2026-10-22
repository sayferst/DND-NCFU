"""Conserved purchases/sales for generated merchants; all prices calculated locally."""

import json
from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.catalog import Entity, validate_plan_properties
from rpg_vkr.domain.interactions import InteractiveWorld, Step, WorldPlan, apply_plan, label
from rpg_vkr.domain.resources import activate, project, properties, reconcile
from rpg_vkr.domain.world import WorldState


@dataclass(frozen=True)
class TradeRecord:
    operation: str
    merchant_id: str
    item_id: str
    quantity: int
    price_gold: int
    base_turn: int
    source: str
    before: InteractiveWorld
    after: InteractiveWorld
    world_before: WorldState
    world_after: WorldState
    merchant_before: Entity
    merchant_after: Entity
    summary: str
    version: str = "trade-homebrew-1"

    def to_dict(self):
        return asdict(self) | {"before": self.before.to_dict(), "after": self.after.to_dict()}


def merchant(catalog, id):
    entity = next((e for e in catalog.entities if e.id == id), None)
    if not entity:
        raise ValueError("Торговец не зарегистрирован.")
    definition = next(d for d in catalog.definitions if d.id == entity.definition_id)
    if definition.kind != "actor" or not (
        definition.properties.get("class")
        in {"merchant", "trader", "shopkeeper", "торговец", "купец"}
        or definition.properties.get("can_trade") is True
    ):
        raise ValueError("Персонаж не предлагает торговлю.")
    state = entity.state or {}
    if (
        state.get("hp", definition.properties["hp_max"]) <= 0
        or state.get("disposition") == "hostile"
    ):
        raise ValueError("Сейчас с этим персонажем нельзя торговать.")
    return entity


def transact(
    catalog,
    scene,
    world,
    merchant_id,
    item_id,
    operation,
    quantity,
    turn_index,
    source,
    aliases=None,
):
    if operation not in {"buy", "sell"} or type(quantity) is not int or not 1 <= quantity <= 1000:
        raise ValueError("Неверная сделка или количество.")
    label(source, 160)
    owner = merchant(catalog, merchant_id)
    if not any(a.id == merchant_id and a.place == scene.current for a in scene.actor_refs):
        raise ValueError("Торговца нет рядом.")
    before = scene
    scene = activate(scene, world, catalog, aliases)
    item = next((t for t in scene.things if t.id == item_id), None)
    if not item or quantity > item.quantity or item.resource == "gold":
        raise ValueError("Такого товара нет в указанном количестве.")
    holder = scene.root_holder(item)
    if holder != (merchant_id if operation == "buy" else "hero"):
        raise ValueError("Товар не находится у продавца.")
    if operation == "sell" and item.owner not in {"", "hero"}:
        raise ValueError("Торговец не покупает чужую собственность.")
    if item.container and any(t.holder == item.id for t in scene.things):
        raise ValueError("Сначала освободите контейнер: цена его содержимого не включена.")
    mapping = {e.id: e.definition_id for e in catalog.entities}
    for key, origin in (aliases or {}).items():
        if origin in mapping:
            mapping[key] = mapping[origin]
    type_id = "type_bandage" if item.resource == "bandages" else mapping.get(item.id)
    definition = next((d for d in catalog.definitions if d.id == type_id), None)
    if not definition or definition.price_cp is None or definition.price_cp < 1:
        raise ValueError("Для предмета пока нет цены.")
    price = (
        (definition.price_cp * quantity + 99) // 100
        if operation == "buy"
        else definition.price_cp * quantity // 200
    )
    if not price:
        raise ValueError("Цена ниже одной золотой; мелкая разменная валюта пока не используется.")
    wallet = (owner.state or {}).get("gold_cp", 0)
    if type(wallet) is not int or wallet < 0:
        raise ValueError("Неверное состояние кошелька торговца.")
    available = project(scene, world)
    merchant_coins = []
    by_id = {t.id: t for t in scene.things}
    for coin in scene.things:
        if coin.resource != "gold" or scene.root_holder(coin) != merchant_id:
            continue
        cursor, blocked = coin, False
        while cursor.holder in by_id:
            cursor = by_id[cursor.holder]
            if properties(scene, cursor.id, catalog).get("locked"):
                blocked = True
        if not blocked:
            merchant_coins.append(coin)
    available_wallet = wallet + sum(t.quantity * 100 for t in merchant_coins)
    if (
        operation == "buy"
        and available.gold < price
        or operation == "sell"
        and available_wallet < price * 100
    ):
        raise ValueError("Для сделки не хватает денег.")
    step = Step(
        "take" if operation == "buy" else "give",
        item_id,
        quantity,
        "" if operation == "buy" else merchant_id,
    )
    plan = WorldPlan((step,))
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
    projected = project(moved, world)
    after_world = replace(
        projected, gold=projected.gold + (price if operation == "sell" else -price)
    )
    moved = reconcile(moved, projected, after_world, turn_index, catalog)
    state = dict(owner.state or {})
    state["gold_cp"] = wallet + (price * 100 if operation == "buy" else -price * 100)
    if state["gold_cp"] < 0:
        required = (-state["gold_cp"] + 99) // 100
        remaining = required
        things = list(moved.things)
        for coin in merchant_coins:
            amount = min(remaining, coin.quantity)
            things.remove(coin)
            if amount < coin.quantity:
                things.append(replace(coin, quantity=coin.quantity - amount))
            remaining -= amount
            if not remaining:
                break
        moved = replace(moved, things=tuple(things))
        state["gold_cp"] += required * 100
    after_owner = replace(owner, state=state)
    result = replace(
        catalog, entities=tuple(after_owner if e.id == owner.id else e for e in catalog.entities)
    )
    summary = ("Куплено" if operation == "buy" else "Продано") + f": {item.name} ×{quantity}. "
    summary += ("Потрачено" if operation == "buy" else "Получено") + f" {price} золотых."
    record = TradeRecord(
        operation,
        merchant_id,
        item_id,
        quantity,
        price,
        turn_index - 1,
        source,
        before,
        moved,
        world,
        after_world,
        owner,
        after_owner,
        summary,
    )
    return result, after_world, record


def restore_trade(data, catalog, aliases):
    if not isinstance(data, dict) or set(data) != set(TradeRecord.__dataclass_fields__):
        raise ValueError("Неверная запись сделки.")
    before = InteractiveWorld.from_dict(data["before"])
    world = WorldState.from_dict(data["world_before"])
    result, _, record = transact(
        catalog,
        before,
        world,
        data["merchant_id"],
        data["item_id"],
        data["operation"],
        data["quantity"],
        data["base_turn"] + 1,
        data["source"],
        aliases,
    )
    if json.loads(json.dumps(record.to_dict())) != json.loads(json.dumps(data)):
        raise ValueError("Сделка не соответствует расчёту движка.")
    return result, record
