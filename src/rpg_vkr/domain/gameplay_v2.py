"""Second playable revision: physical equipment bridge and a single copper market.

v1 calculations remain in gameplay.py and are always used to replay schema24.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256

from rpg_vkr.domain import gameplay as v1
from rpg_vkr.domain.catalog import Catalog, seed_catalog
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.combat import CombatState
from rpg_vkr.domain.d20_progression import D20Progress, level_for_xp
from rpg_vkr.domain.hero_resources import COSTS, refresh
from rpg_vkr.domain.interactions import InteractiveWorld
from rpg_vkr.domain.resources import accessible, reconcile, type_mapping
from rpg_vkr.domain.world import WorldState

VERSION = "gameplay-v3-playable-2"
CATALOG_VERSION = "gameplay-catalog-2"
TALENTS = v1.TALENTS | {
    "resilient": "Крепкий: +2 к максимуму HP",
    "enduring": "Выносливый: +4 к максимуму ST",
    "focus": "Сосредоточенный: +4 к максимуму MP после доступа к магии",
}
LEGACY_KINDS = {"type_training_sword": "sword", "type_knife": "dagger", "type_staff": "short_sword"}
MATERIALS = {
    "mat_iron": "iron",
    "mat_linen": "cloth",
    "mat_wool": "cloth",
    "mat_silk": "cloth",
    "type_healing_herb": "herb",
}


def initial(identity, character):
    if not isinstance(identity, dict) or identity.get("talent", "") not in {"", *TALENTS}:
        raise ValueError("Неизвестный начальный талант.")
    translated = identity | {
        "talent": identity.get("talent", "") if identity.get("talent", "") in v1.TALENTS else ""
    }
    state = v1.initial(translated, character)
    state["identity"] = deepcopy(identity)
    state["talents"] = [identity["talent"]] if identity.get("talent") else []
    state.update(version=VERSION, catalog_version=CATALOG_VERSION, world_aliases={})
    state, _ = refresh(state, WorldState(), character, 1, initial=True)
    return state


def name(item):
    return item.get("name") or v1.ITEM_NAMES[item["kind"]]


def aliases(turns):
    result = {}
    for index, turn in enumerate(turns, 1):
        if turn.interaction:
            result.update(
                {f"split_{index}_{j}": s.target for j, s in enumerate(turn.interaction.plan.steps)}
            )
        if turn.trade:
            result[f"split_{index}_0"] = turn.trade.item_id
        if turn.gameplay:
            result.update(turn.gameplay["result"]["state"].get("world_aliases", {}))
    return result


def equipment_kind(definition):
    props = definition.properties
    if definition.effects or props.get("attack_bonus", 0) != 0 or props.get("damage_bonus", 0) != 0:
        raise ValueError("Эффекты и бонусы этого предмета ещё не поддержаны обработчиком.")
    if props.get("equipment_slot") == "shield" or props.get("shield") is True:
        if props.get("shield_bonus", 2) != 2:
            raise ValueError("Нестандартный бонус щита не поддержан.")
        return "shield"
    if (
        isinstance(props.get("armour"), str)
        and props["armour"] in v1.ARMOUR
        and props["armour"] != "none"
    ):
        return props["armour"]
    if isinstance(props.get("weapon"), str) and props["weapon"] in v1.WEAPONS:
        if (
            props.get("damage_dice", v1.WEAPONS[props["weapon"]][0])
            != v1.WEAPONS[props["weapon"]][0]
        ):
            raise ValueError("Карточка оружия содержит несовместимые кубики урона.")
        if props.get("hands", v1.WEAPONS[props["weapon"]][1]) != v1.WEAPONS[props["weapon"]][1]:
            raise ValueError("Карточка оружия содержит несовместимое число рук.")
        return props["weapon"]
    if definition.id in LEGACY_KINDS:
        return LEGACY_KINDS[definition.id]
    expression = props.get("damage_dice")
    hands = props.get("hands", 1)
    ranged = props.get("range_m", 1)
    if type(hands) is not int or type(ranged) is not int:
        raise ValueError("Неверные свойства оружия.")
    candidates = [
        k
        for k, (dice, grip) in v1.WEAPONS.items()
        if dice == expression and grip == hands and (k in {"longbow", "crossbow"}) == (ranged > 1)
    ]
    if not candidates:
        raise ValueError("У предмета нет поддержанной карточки оружия, доспеха или щита.")
    return candidates[0]


def contact(state, catalog, scene, combat, id):
    entity = next((e for e in catalog.entities if e.id == id), None)
    definition = next(
        (d for d in catalog.definitions if entity and d.id == entity.definition_id), None
    )
    if not any(
        a.id == id and a.place == scene.current for a in scene.actor_refs
    ) or not v1.available(state, id, definition):
        raise ValueError("Торговец отсутствует или лавка закрыта.")
    if id == "merchant" and entity is None:
        actor = combat.actor(id)
        if actor.hp <= 0 or actor.disposition == "hostile":
            raise ValueError("Торговец недоступен.")
    else:
        from rpg_vkr.domain.trade import merchant

        merchant(catalog, id)
    return entity


def _execute(state, command, args, context, dice):
    if state.get("version") != VERSION or state.get("catalog_version") != CATALOG_VERSION:
        raise ValueError("Неизвестная версия новых правил.")
    if not isinstance(command, str) or not isinstance(args, dict):
        raise ValueError("Неверная команда или параметры.")
    if command == "buy" and not any(i["id"] == args.get("item") for i in state["items"]):
        if args.get("merchant") != "merchant":
            raise ValueError("У торговца нет подтверждённого товара. Выберите предмет мира.")
    if not isinstance(context.get("aliases"), dict):
        raise ValueError("Не задана история физических экземпляров.")
    if len(context["aliases"]) > 10000 or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in context["aliases"].items()
    ):
        raise ValueError("Неверная история происхождения экземпляров.")
    extra_talent = (
        command == "talent"
        and args.get("talent") in TALENTS
        and args.get("talent") not in v1.TALENTS
    )
    if (
        command not in {"adopt", "trade_world", "prepare"}
        and not extra_talent
        and not (
            command in {"buy", "sell"}
            and any(i["id"] == args.get("item") and "source" in i for i in state["items"])
        )
    ):
        translated = deepcopy(state)
        translated.update(version=v1.VERSION, catalog_version=v1.CATALOG_VERSION)
        result = v1.execute(translated, command, args, context, dice)
        result["state"].update(version=VERSION, catalog_version=CATALOG_VERSION)
        return result
    signatures = {
        "adopt": {"item"},
        "prepare": {"item"},
        "trade_world": {"merchant", "item", "operation", "quantity"},
        "talent": {"talent"},
        "buy": {"merchant", "item"},
        "sell": {"merchant", "item"},
    }
    if not isinstance(args, dict) or set(args) != signatures[command]:
        raise ValueError("Неверные параметры операции с физическим предметом.")
    state = deepcopy(state)
    world = WorldState.from_dict(context["world"])
    combat = CombatState.from_dict(context["combat"])
    scene = InteractiveWorld.from_dict(context["scene"])
    catalog = Catalog.from_dict(context["catalog"]) if context["catalog"] else seed_catalog()
    if world.hp <= 0 or combat.active or state["active"] or not catalog:
        raise ValueError("Операция недоступна в бою, после выбытия или без каталога.")
    v1.ensure_names(state, catalog)
    message, transaction, duration = "", None, 1
    if command == "talent":
        progress = D20Progress.from_dict(context["progress"])
        key = args["talent"]
        if key in state["talents"] or len(state["talents"]) >= progress.talent_rewards:
            raise ValueError("Талант уже получен или нет награды уровня.")
        state["talents"].append(key)
        message = "Получен талант: " + TALENTS[key]
    elif command in {"adopt", "prepare"}:
        thing = next((t for t in scene.things if t.id == args["item"]), None)
        mapping = type_mapping(catalog, context["aliases"])
        definition = next(
            (d for d in catalog.definitions if thing and d.id == mapping.get(thing.id)), None
        )
        if (
            not thing
            or not definition
            or thing.owner not in {"", "hero"}
            or thing.container
            or thing.resource
            or not accessible(scene, thing, catalog)
        ):
            raise ValueError("Предмет должен находиться в доступном собственном инвентаре.")
        kind = MATERIALS.get(definition.id) if command == "prepare" else equipment_kind(definition)
        if not kind:
            raise ValueError("Материал не входит в каталог мастерской.")
        # The old entity remains a type/provenance reference for split stacks, not a live copy.
        id = "adopt_" + sha256(f"{thing.id}:{context['turn']}".encode()).hexdigest()[:24]
        value = v1.item(id, kind)
        if command == "adopt":
            from rpg_vkr.domain.copper_trade import source_entity

            entity = source_entity(catalog, thing.id, context["aliases"])
            props = (entity.state or {}) if entity else {}
            maximum = definition.properties.get("durability", 20)
            current = props.get("condition", maximum)
            if (
                type(maximum) is not int
                or maximum < 1
                or type(current) is not int
                or not 0 <= current <= maximum
            ):
                raise ValueError("Неверное состояние исходного предмета.")
            value.update(
                name=thing.name,
                price_cp=definition.price_cp,
                durability=current * 20 // maximum,
                source={
                    "thing": asdict(thing),
                    "definition": definition.to_dict(),
                    "condition": current,
                    "maximum": maximum,
                },
            )
        state["items"].append(value)
        scene = replace(
            scene,
            things=tuple(
                replace(t, quantity=t.quantity - 1) if t.id == thing.id else t
                for t in scene.things
                if t.id != thing.id or t.quantity > 1
            ),
        )
        message = (
            "В снаряжение передан" if command == "adopt" else "Подготовлен материал"
        ) + f": {thing.name} ×1. Исходная единица израсходована."
    elif command == "trade_world":
        from rpg_vkr.domain.copper_trade import transact_copper

        contact(state, catalog, scene, combat, args["merchant"])
        catalog, scene, world, state["copper"], transaction = transact_copper(
            catalog,
            scene,
            world,
            state["copper"],
            args["merchant"],
            args["item"],
            args["operation"],
            args["quantity"],
            context["turn"],
            context["aliases"],
            100 + state["minute"] // 1440 % 3 * 10,
        )
        if transaction["moved_id"] != args["item"]:
            state["world_aliases"][transaction["moved_id"]] = args["item"]
        message = (
            "Куплено" if args["operation"] == "buy" else "Продано"
        ) + f": {transaction['name']} ×{args['quantity']}. Цена {transaction['price_cp']} медных."
        duration = 5
    else:
        entity = contact(state, catalog, scene, combat, args["merchant"])
        value = next((i for i in state["items"] if i["id"] == args["item"]), None)
        if not value or value["owner"] != (args["merchant"] if command == "buy" else "hero"):
            raise ValueError("Предмет не находится у продавца.")
        if value["id"] in (state["weapon"], state["armour"], state["shield"]):
            raise ValueError("Сначала снимите предмет.")
        if type(value.get("price_cp")) is not int or value["price_cp"] < 1:
            raise ValueError("Для исходного предмета нет цены.")
        base = value["price_cp"] * value["durability"] // 20
        price = (
            (base * (100 + state["minute"] // 1440 % 3 * 10) + 99) // 100
            if command == "buy"
            else base // 2
        )
        wallet = (
            (entity.state or {}).get("gold_cp", 0)
            if entity
            else world.shop_gold * 100 + state.get("shop_copper", 0)
        )
        total = world.gold * 100 + state["copper"]
        if price <= 0 or command == "buy" and total < price or command == "sell" and wallet < price:
            raise ValueError("Для сделки не хватает денег или цены.")
        delta = -price if command == "buy" else price
        before = world
        total += delta
        world = replace(world, gold=total // 100)
        state["copper"] = total % 100
        value["owner"] = "hero" if command == "buy" else args["merchant"]
        if entity:
            changed = replace(entity, state=(entity.state or {}) | {"gold_cp": wallet - delta})
            catalog = replace(
                catalog,
                entities=tuple(changed if e.id == entity.id else e for e in catalog.entities),
            )
        else:
            world = replace(world, shop_gold=(wallet - delta) // 100)
            state["shop_copper"] = (wallet - delta) % 100
        scene = reconcile(scene, before, world, context["turn"], catalog)
        transaction = {
            "operation": command,
            "merchant": args["merchant"],
            "item": value["id"],
            "moved_id": value["id"],
            "quantity": 1,
            "price_cp": price,
            "name": name(value),
        }
        message = f"Сделка: {name(value)}, {price} медных."
        duration = 5
    translated = deepcopy(state)
    translated.update(version=v1.VERSION, catalog_version=v1.CATALOG_VERSION)
    after_context = context | {
        "world": asdict(world),
        "scene": scene.to_dict(),
        "catalog": catalog.to_dict() if context["catalog"] or catalog != seed_catalog() else None,
    }
    result = v1.execute(translated, "wait", {"minutes": duration}, after_context, dice)
    result["state"].update(version=VERSION, catalog_version=CATALOG_VERSION)
    result["text"] = message + "\n" + result["text"]
    if transaction:
        result["transaction"] = transaction
    return result


def execute(state, command, args, context, dice):
    if not isinstance(command, str) or not isinstance(args, dict):
        raise ValueError("Неверная команда или параметры.")
    character = Character.from_dict(context["character"])
    progress = D20Progress.from_dict(context["progress"])
    prepared, world = refresh(
        state, WorldState.from_dict(context["world"]), character, progress.level
    )
    cost = 1 if command == "advance" and args.get("minutes", 0) >= 10 else COSTS.get(command, 0)
    if prepared["st"] < cost:
        raise ValueError("Недостаточно ST. Отступите и отдохните.")
    result = _execute(prepared, command, args, context | {"world": asdict(world)}, dice)
    gained = len(set(result["state"]["victories"]) - set(state["victories"])) * 50
    level = level_for_xp(progress.xp + gained)
    state_after, world_after = refresh(
        result["state"],
        WorldState.from_dict(result["world"]),
        character,
        level,
        rest=command == "rest",
    )
    if (
        command in {"attack", "cast"}
        and world_after.hp == 0
        and not any(a["actor_id"] == "hero" for a in result["attacks"])
    ):
        cost = 0
    state_after["st"] -= cost
    if world_after.trading and not v1.available(state_after, "merchant"):
        world_after = replace(world_after, trading=False)
    result["state"], result["world"] = state_after, asdict(world_after)
    if cost:
        result["text"] += (
            f"\nПотрачено {cost} ST; осталось {state_after['st']}/{state_after['st_cap']}."
        )
    if level > progress.level:
        result["text"] += (
            f"\nДостигнут уровень {level}. HP {world_after.hp}/{world_after.max_hp}, "
            f"ST {state_after['st']}/{state_after['st_cap']}."
        )
    return result
