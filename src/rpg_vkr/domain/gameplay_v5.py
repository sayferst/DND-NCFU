"""Integrated final catalog revision: creation, schools I–V, production and living world."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain import gameplay_v4 as previous
from rpg_vkr.domain.catalog import Catalog
from rpg_vkr.domain.character import Character, ability_modifier
from rpg_vkr.domain.combat import ACTORS, CombatState
from rpg_vkr.domain.content_v5 import (
    ABILITIES,
    ITEMS,
    KITS,
    PRICES,
    RECIPES,
    SPELLS,
    identity,
    inherited,
    make_item,
)
from rpg_vkr.domain.d20_progression import D20Progress
from rpg_vkr.domain.gameplay_v2 import contact
from rpg_vkr.domain.hero_resources import refresh
from rpg_vkr.domain.interactions import InteractiveWorld
from rpg_vkr.domain.resources import reconcile
from rpg_vkr.domain.world import WorldState
from rpg_vkr.domain.world_v5 import advance, initialize

VERSION = "gameplay-v3-playable-5"
CATALOG_VERSION = "gameplay-catalog-5"


def initial(value, character):
    value = identity(value)
    old = {k: v for k, v in value.items() if k not in {"kit", "starting_spells"}}
    state = previous.initial(old, character)
    state.update(
        version=VERSION,
        catalog_version=CATALOG_VERSION,
        identity=value,
        living_world=None,
        ability_uses={},
        content_sequence=0,
    )
    weapon, extras = KITS[value["kit"]][1:]
    state["items"][0].update(kind=weapon, name=ITEMS[weapon], price_cp=PRICES[weapon])
    state["items"] = [i for i in state["items"] if i["kind"] not in {"herb", "iron", "cloth"}]
    for kind in (*extras, "wood", "wood"):
        state["items"].append(make_item(f"creation_{len(state['items'])}", kind))
    state["spells"] = list(value["starting_spells"])
    state, _ = refresh(state, WorldState(), inherited(character, state), 1, initial=True)
    return state


def parent(state, command, args, context, dice):
    candidate = deepcopy(state)
    candidate.update(version=previous.VERSION, catalog_version=previous.CATALOG_VERSION)
    result = previous.execute(candidate, command, args, context, dice)
    result["state"].update(version=VERSION, catalog_version=CATALOG_VERSION)
    return result


def execute(original, command, args, context, dice):
    if original.get("version") != VERSION or original.get("catalog_version") != CATALOG_VERSION:
        raise ValueError("Неизвестный каталог новых правил.")
    if not isinstance(command, str) or not isinstance(args, dict):
        raise ValueError("Неверная команда.")
    state = deepcopy(original)
    character = inherited(Character.from_dict(context["character"]), state)
    internal = context | {"character": asdict(character)}
    world = WorldState.from_dict(context["world"])
    before = world
    scene = InteractiveWorld.from_dict(context["scene"])
    catalog = Catalog.from_dict(context["catalog"]) if context["catalog"] else None
    combat = CombatState.from_dict(context["combat"])
    progress = D20Progress.from_dict(context["progress"])
    initialize(state, catalog, scene)
    own = command in {"ability", "manufacture", "gather", "consume", "supply", "diplomacy"}
    own |= (
        command in {"learn", "cast"}
        and isinstance(args.get("spell"), str)
        and args["spell"] in SPELLS
    )
    value = next((i for i in state["items"] if i["id"] == args.get("item")), None)
    own |= command in {"buy", "sell"} and value is not None
    if own:
        if world.hp <= 0 or combat.active:
            raise ValueError("Действие недоступно после выбытия.")
        if state.get("battle") and command not in {"consume", "cast", "ability"}:
            raise ValueError("Сначала завершите бой.")
        duration, cost, message, event = 5, 1, "", None

        def consume_materials(requirements):
            selected = []
            for kind, amount in requirements.items():
                found = [
                    i
                    for i in state["items"]
                    if i["owner"] == "hero"
                    and i["kind"] == kind
                    and i["id"] not in selected
                    and i["id"] not in {state["weapon"], state["armour"], state["shield"]}
                ]
                if len(found) < amount:
                    raise ValueError("Не хватает материала: " + ITEMS[kind])
                selected.extend(i["id"] for i in found[:amount])
            state["items"] = [i for i in state["items"] if i["id"] not in selected]

        def add(kind, quality=1):
            state["content_sequence"] += 1
            state["items"].append(
                make_item(
                    f"content_{context['turn']}_{state['content_sequence']}", kind, quality=quality
                )
            )

        if command == "ability":
            if args:
                raise ValueError("Способность профиля не требует параметров.")
            key = state["identity"]["profile"]
            name, field, amount = ABILITIES[key]
            day = state["minute"] // 1440
            if state["ability_uses"].get(key) == day:
                raise ValueError("Способность уже использована сегодня.")
            if field == "hp":
                if world.hp == world.max_hp:
                    raise ValueError("Здоровье полное.")
                world = replace(world, hp=min(world.max_hp, world.hp + amount))
            else:
                if state[field] >= state[field + "_cap"]:
                    raise ValueError("Ресурс уже полон.")
                state[field] = min(state[field + "_cap"], state[field] + amount)
            state["ability_uses"][key] = day
            message = name + ": ресурс восстановлен, способность использована на сегодня."
        elif command == "gather":
            if set(args) != {"material", "quantity"} or args["material"] not in {
                "wood",
                "iron",
                "herb",
            }:
                raise ValueError("Выберите материал и количество.")
            amount = args["quantity"]
            if type(amount) is not int or not 1 <= amount <= 10:
                raise ValueError("Количество1–10.")
            node = state["living_world"]["nodes"][scene.current]
            if node[args["material"]] < amount:
                raise ValueError("Доступный запас исчерпан.")
            if args["material"] == "iron" and progress.rank("smithing") < 1:
                raise ValueError("Для добычи железа нужен ранг Кузнечного дела1.")
            if not any(
                i["owner"] == "hero" and i["kind"] == "tools" and i["durability"]
                for i in state["items"]
            ):
                raise ValueError("Нужны исправные инструменты.")
            node[args["material"]] -= amount
            for _ in range(amount):
                add(args["material"])
            duration, cost = 10 * amount, 2
            message = f"Добыто {amount}: {ITEMS[args['material']]}. Запас местности уменьшен."
        elif command == "manufacture":
            if set(args) != {"recipe", "quality"} or args["recipe"] not in RECIPES:
                raise ValueError("Выберите рецепт и качество.")
            recipe = RECIPES[args["recipe"]]
            quality = args["quality"]
            if type(quality) is not int or not 1 <= quality <= 3:
                raise ValueError("Качество1–3.")
            if progress.rank(recipe["skill"]) < max(recipe["rank"], 2 * (quality - 1)):
                raise ValueError("Недостаточный ранг навыка для рецепта/качества.")
            station = next(
                (
                    i
                    for i in state["items"]
                    if i["owner"] == "hero" and i["kind"] == recipe["station"] and i["durability"]
                ),
                None,
            )
            if not station:
                raise ValueError("Требуется исправная станция: " + ITEMS[recipe["station"]])
            consume_materials(recipe["inputs"])
            station["durability"] -= 1
            add(recipe["output"], quality)
            duration, cost, message = (
                recipe["minutes"],
                3,
                recipe["name"] + ": изделие создано, материалы израсходованы.",
            )
        elif command in {"learn", "cast"}:
            if set(args) != ({"spell"} if command == "learn" else {"spell", "target"}):
                raise ValueError("Неверные параметры магии.")
            key, spell = args["spell"], SPELLS[args["spell"]]
            if command == "learn":
                if (
                    key in state["spells"]
                    or progress.rank("arcana") < spell["rank"]
                    or progress.level < spell["level"]
                ):
                    raise ValueError("Заклинание уже известно либо недостаточны ранг/уровень.")
                if not any(
                    i["kind"] == "focus" and i["owner"] == "hero" and i["durability"]
                    for i in state["items"]
                ):
                    raise ValueError("Нужен исправный фокус.")
                state["spells"].append(key)
                duration, cost, message = 60, 0, "Изучено: " + spell["name"]
            else:
                if key not in state["spells"] or state["mp"] < spell["mp"]:
                    raise ValueError("Заклинание не изучено или недостаточно MP.")
                if not any(
                    i["kind"] == "focus" and i["owner"] == "hero" and i["durability"]
                    for i in state["items"]
                ):
                    raise ValueError("Нужен исправный фокус.")
                target = args["target"]
                if not isinstance(target, str):
                    raise ValueError("Неверная цель.")
                entity = (
                    next((e for e in catalog.entities if e.id == target), None) if catalog else None
                )
                model = (
                    next(
                        (d for d in catalog.definitions if entity and d.id == entity.definition_id),
                        None,
                    )
                    if catalog
                    else None
                )
                hp = (
                    world.hp
                    if target == "hero"
                    else (entity.state or {}).get("hp", model.properties["hp_max"])
                    if entity and model
                    else 0
                )
                maximum = (
                    world.max_hp if target == "hero" else model.properties["hp_max"] if model else 0
                )
                if hp <= 0 or not (
                    target == "hero"
                    or any(r.id == target and r.place == scene.current for r in scene.actor_refs)
                ):
                    raise ValueError("Цель отсутствует или выбыла.")
                if spell["effect"] == "attack":
                    battle = state.get("battle")
                    if not battle or battle["sides"].get(target) != "enemy":
                        raise ValueError("Для атаки начните бой с этой целью.")
                    if (
                        abs(battle["positions"]["hero"] - battle["positions"][target])
                        > spell["range"]
                    ):
                        raise ValueError("Цель вне дальности.")
                elif spell["effect"] != "heal" and target != "hero":
                    raise ValueError("Этот эффект применяется к герою.")
                if spell["effect"] == "heal" and hp == maximum:
                    raise ValueError("Здоровье цели полное.")
                if spell["effect"] == "ward" and any(e["kind"] == "ward" for e in state["effects"]):
                    raise ValueError("Защита уже действует.")
                consume_materials({"herb": spell["components"]})
                state["mp"] -= spell["mp"]
                if spell["effect"] in {"attack", "heal"}:
                    raw = []
                    if spell["effect"] == "attack":
                        save = dice.roll_d20()
                        raw.append(asdict(save))
                        success = save.value + ability_modifier(
                            model.properties.get("dexterity", 10)
                        ) < 8 + ability_modifier(character.intelligence) + 2 * progress.rank(
                            "arcana"
                        )
                    else:
                        success = True
                    start = dice.checkpoint()[1]
                    roll = dice.roll(spell["dice"], reason=spell["name"])
                    raw.extend(
                        {"index": start + n + 1, "value": v}
                        for n, v in enumerate(roll.individual_rolls)
                    )
                    amount = (
                        max(
                            0,
                            roll.total
                            + (
                                ability_modifier(character.intelligence)
                                if spell["effect"] == "heal"
                                else 0
                            ),
                        )
                        if success
                        else 0
                    )
                    after = (
                        max(0, hp - amount)
                        if spell["effect"] == "attack"
                        else min(maximum, hp + amount)
                    )
                    if target == "hero":
                        world = replace(world, hp=after)
                    else:
                        values = (entity.state or {}) | {"hp": after}
                        if after == 0:
                            values["life"] = "unconscious"
                            if target not in state["victories"]:
                                state["victories"].append(target)
                        catalog = replace(
                            catalog,
                            entities=tuple(
                                replace(e, state=values) if e.id == target else e
                                for e in catalog.entities
                            ),
                        )
                        if target in ACTORS:
                            combat = combat.update(replace(combat.actor(target), hp=after))
                    event = {
                        "kind": "spell",
                        "actor": "hero",
                        "target": target,
                        "damage": amount if spell["effect"] == "attack" else 0,
                        "hp_after": after,
                        "rolls": raw,
                    }
                else:
                    state["effects"].append(
                        {"kind": spell["effect"], "expires": state["minute"] + spell["duration"]}
                    )
                duration, message = 1, spell["name"] + f": потрачено {spell['mp']} MP."
        elif command == "consume":
            if (
                set(args) != {"item"}
                or not value
                or value["owner"] != "hero"
                or value["kind"] not in {"potion", "meal", "crystal", "rune"}
            ):
                raise ValueError("Выберите принадлежащий герою расходуемый предмет.")
            kind, quality = value["kind"], value.get("quality", 1)
            if kind == "potion":
                if world.hp == world.max_hp:
                    raise ValueError("Здоровье полное.")
                world = replace(world, hp=min(world.max_hp, world.hp + 8 * quality))
            elif kind == "rune":
                if any(e["kind"] == "ward" for e in state["effects"]):
                    raise ValueError("Защита уже действует.")
                state["effects"].append({"kind": "ward", "expires": state["minute"] + 20 * quality})
            else:
                field, amount = ("st", 5) if kind == "meal" else ("mp", 6)
                if state[field] >= state[field + "_cap"]:
                    raise ValueError("Ресурс уже полон.")
                state[field] = min(state[field + "_cap"], state[field] + amount * quality)
            state["items"].remove(value)
            duration, message = 1, ITEMS[kind] + ": предмет израсходован."
        elif command in {"buy", "sell"}:
            if set(args) != {"item", "merchant"}:
                raise ValueError("Неверная сделка.")
            trader = contact(state, catalog, scene, combat, args["merchant"])
            if not trader or value["owner"] != (args["merchant"] if command == "buy" else "hero"):
                raise ValueError("Предмет не принадлежит продавцу.")
            if value["id"] in {state["weapon"], state["armour"], state["shield"]}:
                raise ValueError("Сначала снимите снаряжение.")
            base_price = value.get("price_cp", PRICES[value["kind"]]) * value["durability"] // 20
            price = max(1, base_price) if command == "buy" else base_price // 2
            from rpg_vkr.domain.factions import tax_recipient

            authority = tax_recipient(state)
            duty = (price * 5 + 99) // 100 if authority and command == "buy" else 0
            coins, wallet = (
                world.gold * 100 + state["copper"],
                (trader.state or {}).get("gold_cp", 0),
            )
            if (
                price <= 0
                or command == "buy"
                and coins < price + duty
                or command == "sell"
                and wallet < price
            ):
                raise ValueError("Недостаточно монет.")
            delta = -(price + duty) if command == "buy" else price
            coins += delta
            wallet += price if command == "buy" else -price
            world = replace(world, gold=coins // 100)
            state["copper"] = coins % 100
            if duty:
                authority["treasury_cp"] += duty
            catalog = replace(
                catalog,
                entities=tuple(
                    replace(e, state=(e.state or {}) | {"gold_cp": wallet})
                    if e.id == trader.id
                    else e
                    for e in catalog.entities
                ),
            )
            value["owner"] = "hero" if command == "buy" else trader.id
            cost, message = 0, f"Сделка: {price + duty if command == 'buy' else price} медных."
            event = {
                "transaction": {
                    "operation": command,
                    "price_cp": price + duty if command == "buy" else price,
                    "base_price_cp": price,
                    "duty_cp": duty,
                    "merchant": trader.id,
                    "item_id": value["id"],
                }
            }
        elif command in {"supply", "diplomacy"}:
            from rpg_vkr.domain.factions import contact as faction_contact

            expected = (
                {"faction", "material", "quantity"} if command == "supply" else {"faction", "other"}
            )
            if set(args) != expected:
                raise ValueError("Неверные параметры фракции.")
            faction = faction_contact(state, catalog, scene, args["faction"])
            if command == "supply":
                kind, amount = args["material"], args["quantity"]
                if (
                    kind not in {"wood", "iron", "herb", "meal"}
                    or type(amount) is not int
                    or not 1 <= amount <= 10
                ):
                    raise ValueError("Недопустимая поставка.")
                price = PRICES[kind] * amount // 2
                if faction["treasury_cp"] < price:
                    raise ValueError("В казне не хватает денег.")
                consume_materials({kind: amount})
                stock = state["living_world"]["stocks"][faction["id"]]
                stock["food" if kind == "meal" else kind] += amount
                faction["treasury_cp"] -= price
                coins = world.gold * 100 + state["copper"] + price
                world = replace(world, gold=coins // 100)
                state["copper"] = coins % 100
                faction["reputation"] = min(100, faction["reputation"] + amount)
                message = f"Поставка принята: {price} медных из казны."
            else:
                other = faction_contact(state, catalog, scene, args["other"])
                if other["id"] == faction["id"]:
                    raise ValueError("Нужны две разные фракции.")
                key = ":".join(sorted([faction["id"], other["id"]]))
                relations = state["living_world"]["relations"]
                relations[key] = min(100, relations.get(key, 0) + 10)
                duration, cost, message = 60, 2, "Переговоры: отношения улучшены на10."
        if state["st"] < cost:
            raise ValueError("Недостаточно ST.")
        state["st"] -= cost
        scene = reconcile(scene, before, world, context["turn"], catalog)
        updated = internal | {
            "world": asdict(world),
            "catalog": catalog.to_dict() if catalog else None,
            "combat": combat.to_dict(),
            "scene": scene.to_dict(),
        }
        # Reuse the established queue once; remove only its temporary recovery credit.
        recovering = state.get("battle") is not None
        credit = min(3, state["st_cap"] - state["st"]) if recovering else 0
        result = parent(
            state,
            "recover" if recovering else "wait",
            {} if recovering else {"minutes": duration},
            updated,
            dice,
        )
        result["state"]["st"] -= credit
        result["text"] = message + "\n" + result["text"]
        if event and "transaction" in event:
            result["transaction"] = event["transaction"]
        elif event:
            result.setdefault("battle_events", []).insert(
                0, {k: v for k, v in event.items() if k != "rolls"}
            )
            result["rolls"] = event.get("rolls", []) + result["rolls"]
    else:
        result = parent(state, command, args, internal, dice)
    # All ordinary actions also reach this deterministic simulator through advance.
    state, catalog, scene, events = advance(
        result["state"],
        Catalog.from_dict(result["catalog"]) if result["catalog"] else None,
        InteractiveWorld.from_dict(result["scene"]),
    )
    result.update(
        state=state, catalog=catalog.to_dict() if catalog else None, scene=scene.to_dict()
    )
    result.setdefault("simulation_events", []).extend(events)
    # Historical tutorial bindings remain read models of their migrated NPC cards.
    combat = CombatState.from_dict(result["combat"])
    if catalog:
        for entity in catalog.entities:
            if entity.id in ACTORS and "hp" in (entity.state or {}):
                hp = entity.state["hp"]
                if hp <= ACTORS[entity.id][2]:
                    combat = combat.update(replace(combat.actor(entity.id), hp=hp))
    result["combat"] = combat.to_dict()
    # Include victories from newly implemented magic in the existing XP/resource curve.
    from rpg_vkr.domain.d20_progression import level_for_xp

    gained = len(set(state["victories"]) - set(original["victories"])) * 50
    state, world = refresh(
        state, WorldState.from_dict(result["world"]), character, level_for_xp(progress.xp + gained)
    )
    result.update(state=state, world=asdict(world))
    return result
