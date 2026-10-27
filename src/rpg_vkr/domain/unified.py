"""Canonical homebrew D20 rules. Old readers never execute this ruleset."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain.catalog import Catalog
from rpg_vkr.domain.character import ABILITY_NAMES, Character, ability_modifier
from rpg_vkr.domain.d20_combat import WEAPONS as OLD_WEAPONS
from rpg_vkr.domain.d20_combat import armour_class
from rpg_vkr.domain.interactions import InteractiveWorld
from rpg_vkr.domain.world import WorldState

WEAPONS = dict(OLD_WEAPONS, focus=("1d6", 2))

VERSION = "dnd-ncfu-unified-d20-v1"
CLASSES = {
    "warrior": (
        "Воин",
        "Ближний бой и броня",
        ("athletics", "melee"),
        (16, 12, 14, 8, 12, 10),
        "duelist",
    ),
    "archer": (
        "Лучник",
        "Стрельба и наблюдательность",
        ("ranged", "perception", "survival"),
        (10, 16, 12, 10, 14, 10),
        "marksman",
    ),
    "rogue": (
        "Плут",
        "Скрытность и инструменты",
        ("stealth", "locks", "acrobatics"),
        (10, 16, 12, 12, 10, 12),
        "subtle",
    ),
    "mage": (
        "Маг",
        "Заклинания и исследования",
        ("arcana", "knowledge"),
        (8, 12, 12, 16, 12, 12),
        "focus",
    ),
    "cleric": (
        "Жрец",
        "Исцеление и духовные ритуалы",
        ("medicine", "faith"),
        (12, 10, 14, 10, 16, 10),
        "healer",
    ),
    "artisan": (
        "Ремесленник",
        "Ремонт и изготовление",
        ("smithing", "repair", "alchemy"),
        (12, 10, 14, 16, 10, 10),
        "craftwise",
    ),
}
TALENTS = {
    "resilient": ("Крепкий", "+2 к максимальному HP"),
    "enduring": ("Неутомимый", "+4 к максимальному ST"),
    "duelist": ("Фехтовальщик", "+1 к атакам ближнего боя"),
    "marksman": ("Меткий", "+1 к атакам из лука"),
    "subtle": ("Ловкач", "+1 к проверкам Ловкости"),
    "keen": ("Чуткий", "+1 к проверкам Мудрости"),
    "eloquent": ("Красноречивый", "+1 к проверкам Харизмы"),
    "versatile": ("Находчивый", "+1 к проверкам характеристик"),
    "focus": ("Сосредоточенный", "+4 к максимальному MP"),
    "healer": ("Целитель", "+1 к восстановлению HP заклинанием"),
    "craftwise": ("Умелец", "+1 к проверкам Интеллекта"),
}
ITEMS = {
    "sword": "Меч",
    "longbow": "Лук",
    "dagger": "Кинжал",
    "shield": "Щит",
    "leather": "Кожаный доспех",
    "focus": "Магический посох",
    "symbol": "Символ веры",
    "tools": "Инструменты",
    "locks": "Отмычки",
    "arrow": "Стрела",
    "bandage": "Бинт",
    "mana": "Малое зелье маны",
    "scroll_light": "Свиток путеводного света",
    "scroll_heal": "Свиток исцеления",
    "iron": "Железо",
    "wood": "Древесина",
    "cloth": "Ткань",
    "herb": "Трава",
    "ingot": "Слиток",
}
KITS = {
    "warrior": ("sword", "shield", "leather", "bandage", "bandage"),
    "archer": ("longbow", "dagger", *("arrow",) * 12, "bandage"),
    "rogue": ("dagger", "locks", "leather", "bandage"),
    "mage": ("focus", "scroll_light", "scroll_heal", "mana", "mana"),
    "cleric": ("dagger", "symbol", "bandage", "bandage"),
    "artisan": ("dagger", "tools", "cloth", "iron", "iron", "wood"),
}
TASKS = {
    "athletics": "strength",
    "melee": "strength",
    "ranged": "dexterity",
    "stealth": "dexterity",
    "locks": "dexterity",
    "acrobatics": "dexterity",
    "perception": "wisdom",
    "survival": "wisdom",
    "arcana": "intelligence",
    "knowledge": "intelligence",
    "smithing": "intelligence",
    "repair": "intelligence",
    "alchemy": "intelligence",
    "medicine": "wisdom",
    "faith": "wisdom",
    "persuasion": "charisma",
    "endure": "constitution",
    **{key: key for key in ABILITY_NAMES},
}
RECIPES = {
    "ingot": ({"iron": 2, "wood": 1}, "smithing", 10),
    "sword": ({"ingot": 2, "wood": 1}, "smithing", 15),
    "mana": ({"herb": 2}, "alchemy", 15),
    "bandage": ({"cloth": 1}, "repair", 5),
}
DC = (5, 10, 15, 20, 25, 30)


def validate_assessment(value):
    from rpg_vkr.domain.campaign import plain

    if not isinstance(value, dict) or set(value) not in (
        {"ability", "dc", "purpose"},
        {"ability", "dc", "purpose", "skill"},
    ):
        raise ValueError("Неверное предложение проверки.")
    if (
        value["ability"] not in ABILITY_NAMES
        or type(value["dc"]) is not int
        or value["dc"] not in DC
    ):
        raise ValueError("Выберите характеристику и сложность5/10/15/20/25/30.")
    plain(value["purpose"], 400)
    if "skill" in value and (
        not isinstance(value["skill"], str)
        or value["skill"] not in TASKS
        or TASKS[value["skill"]] != value["ability"]
    ):
        raise ValueError("Подготовка не соответствует характеристике.")
    return value


def level(xp):
    if type(xp) is not int or xp < 0:
        raise ValueError("Некорректный опыт.")
    return max(lv for lv in range(1, 21) if 50 * (lv - 1) * lv <= xp)


def proficiency(xp):
    return 2 + (level(xp) - 1) // 4


def talents(class_id):
    return ("resilient", "enduring", "keen", "eloquent", "versatile", CLASSES[class_id][4])


def caps(state, character):
    con = ability_modifier(character.constitution)
    strength = ability_modifier(character.strength)
    intelligence = ability_modifier(character.intelligence)
    lv = level(state["xp"])
    return {
        "hp": 16
        + 2 * con
        + max(1, 6 + con) * (lv - 1)
        + (2 if "resilient" in state["talents"] else 0),
        "st": max(10, 20 + 2 * (strength + con))
        + 3 * (lv - 1)
        + (4 if "enduring" in state["talents"] else 0),
        "mp": max(4, 12 + 4 * intelligence + 4 * (lv - 1))
        + (4 if "focus" in state["talents"] else 0)
        if state["identity"]["class_id"] in ("mage", "cleric")
        else 0,
    }


def item(id, kind):
    return {
        "id": id,
        "kind": kind,
        "name": ITEMS[kind],
        "owner": "hero",
        "durability": 20,
        "price_cp": 100,
        "quality": 1,
    }


def initial(identity, character):
    from rpg_vkr.domain.gameplay_v5 import initial as shape
    from rpg_vkr.domain.progression import validate_creation

    validate_creation(character, "fighter")
    if set(identity) != {"class_id", "talent"} or identity["class_id"] not in CLASSES:
        raise ValueError("Выберите класс.")
    key = identity["class_id"]
    if identity["talent"] not in talents(key):
        raise ValueError("Выберите один доступный талант.")
    state = shape(
        {
            "species": "human",
            "profile": "mage",
            "age": 20,
            "background": "Путешественник",
            "appearance": "Дорожная одежда",
            "skills": {},
            "talent": "",
            "kit": "support",
            "starting_spells": [],
        },
        character,
    )
    state.update(
        version=VERSION,
        catalog_version=VERSION,
        identity=deepcopy(identity),
        xp=0,
        ability_increases={},
        rewards=[],
        talents=[identity["talent"]],
        items=[item(f"start_{n}", k) for n, k in enumerate(KITS[key])],
        copper=200,
    )
    state["weapon"] = (
        next(i["id"] for i in state["items"] if i["kind"] in WEAPONS) if key != "mage" else ""
    )
    state["armour"] = next((i["id"] for i in state["items"] if i["kind"] == "leather"), "")
    state["shield"] = next((i["id"] for i in state["items"] if i["kind"] == "shield"), "")
    state["spells"] = (
        ["light", "bolt"] if key == "mage" else ["light", "heal"] if key == "cleric" else []
    )
    limits = caps(state, character)
    state.update(st=limits["st"], st_cap=limits["st"], mp=limits["mp"], mp_cap=limits["mp"])
    return state


def bonus(state, character, task):
    if task not in TASKS:
        raise ValueError("Неизвестный вид проверки.")
    ability = TASKS[task]
    trained = task in CLASSES[state["identity"]["class_id"]][2]
    talent = int(
        ("subtle" in state["talents"] and ability == "dexterity")
        or ("craftwise" in state["talents"] and ability == "intelligence")
    )
    talent += int("keen" in state["talents"] and ability == "wisdom")
    talent += int("eloquent" in state["talents"] and ability == "charisma")
    talent += int("versatile" in state["talents"])
    return ability, ability_modifier(getattr(character, ability)) + (
        proficiency(state["xp"]) if trained else 0
    ) + talent


def execute(original, command, args, context, dice):
    from rpg_vkr.domain.factions import initialize as factions
    from rpg_vkr.domain.factions import simulate
    from rpg_vkr.domain.world_v5 import advance
    from rpg_vkr.domain.world_v5 import initialize as population

    state = deepcopy(original)
    char = Character.from_dict(context["character"])
    world = WorldState.from_dict(context["world"])
    scene = InteractiveWorld.from_dict(context["scene"])
    catalog = Catalog.from_dict(context["catalog"]) if context["catalog"] else None
    if state["version"] != VERSION or not isinstance(args, dict):
        raise ValueError("Неверные правила.")
    allowed = {
        "check": ({"task", "dc"}, {"task", "dc"}),
        "wait": ({"minutes"}, {"minutes"}),
        "advance": ({"minutes"}, {"minutes"}),
        "encounter": ({"enemies", "allies"}, {"enemies"}),
        "attack": ({"target", "lethal"}, {"target"}),
        "recover": (set(), set()),
        "dodge": (set(), set()),
        "cast": ({"spell", "target"}, {"spell", "target"}),
        "consume": ({"item", "target"}, {"item"}),
        "manufacture": ({"recipe", "quality"}, {"recipe"}),
        "repair": ({"item"}, {"item"}),
        "gather": ({"material", "quantity"}, {"material", "quantity"}),
        "equip": ({"item"}, {"item"}),
        "rest": (set(), set()),
        "raise": ({"ability"}, {"ability"}),
        "talent": ({"talent"}, {"talent"}),
        "buy": ({"merchant", "item", "quantity"}, {"merchant", "item"}),
        "sell": ({"merchant", "item", "quantity"}, {"merchant", "item"}),
        "trade_world": (
            {"merchant", "item", "operation", "quantity"},
            {"merchant", "item", "operation"},
        ),
    }
    if command not in allowed or not allowed[command][1] <= set(args) <= allowed[command][0]:
        raise ValueError("Неизвестные параметры действия.")
    if command == "manufacture" and args.get("quality", 1) != 1:
        raise ValueError("В этом каталоге доступно стандартное качество.")
    if world.hp <= 0:
        raise ValueError("Герой выбыл.")
    rolls = []
    attacks = []
    events = []
    text = ""
    duration = 1
    touched_sources = set()

    def roll(expression, reason):
        value = dice.roll(expression, reason=reason)
        rolls.append(asdict(value) | {"index": value.rng_counter})
        return value

    def owned(id):
        value = next((i for i in state["items"] if i["id"] == id and i["owner"] == "hero"), None)
        if not value and catalog:
            entity = next(
                (e for e in catalog.entities if e.id == id and e.owner_id == "hero"), None
            )
            physical = next((t for t in scene.things if t.id == id), None)
            if (
                entity
                and physical
                and scene.root_holder(physical) == "hero"
                and entity.quantity == 1
            ):
                definition = next(d for d in catalog.definitions if d.id == entity.definition_id)
                kind = definition.properties.get(
                    "unified_kind", definition.properties.get("weapon", "miscellaneous")
                )
                if kind not in ITEMS and kind not in WEAPONS:
                    kind = "miscellaneous"
                value = {
                    "id": id,
                    "source": id,
                    "kind": kind,
                    "name": definition.name,
                    "owner": "hero",
                    "durability": 20,
                    "quality": 1,
                    "price_cp": definition.price_cp or 0,
                }
                state["items"].append(value)
        if not value:
            raise ValueError("Предмет не принадлежит герою или недоступен.")
        if value.get("source"):
            touched_sources.add(value["source"])
        return value

    def award(key, amount):
        if key not in state["rewards"]:
            state["rewards"].append(key)
            state["xp"] += amount

    def check(task, dc):
        if type(dc) is not int or dc not in DC:
            raise ValueError("Сложность5/10/15/20/25/30.")
        ability, modifier = bonus(state, char, task)
        value = roll("1d20", task)
        attribute = ability_modifier(getattr(char, ability))
        preparation = (
            proficiency(state["xp"]) if task in CLASSES[state["identity"]["class_id"]][2] else 0
        )
        talent = modifier - attribute - preparation
        return (
            value.total + modifier >= dc,
            f"d20({value.total}) + {ABILITY_NAMES[ability]}({attribute:+}) "
            f"+ подготовка({preparation:+}) + талант({talent:+}) = "
            f"{value.total + modifier} против DC {dc}",
        )

    def actor(id):
        value = next((e for e in catalog.entities if e.id == id), None) if catalog else None
        if not value or not any(a.id == id and a.place == scene.current for a in scene.actor_refs):
            raise ValueError("Участника нет рядом.")
        definition = next(d for d in catalog.definitions if d.id == value.definition_id)
        if definition.kind != "actor" or (value.state or {}).get("hp", 1) <= 0:
            raise ValueError("Участник выбыл.")
        return value, definition

    def hp(id, amount):
        nonlocal world, catalog
        if id == "hero":
            world = replace(world, hp=max(0, min(world.max_hp, world.hp + amount)))
            return world.hp
        value, definition = actor(id)
        data = dict(value.state or {})
        data["hp"] = max(
            0,
            min(
                definition.properties["hp_max"],
                data.get("hp", definition.properties["hp_max"]) + amount,
            ),
        )
        if data["hp"] == 0:
            data["life"] = "unconscious"
        updated = replace(value, state=data)
        catalog = replace(
            catalog, entities=tuple(updated if e.id == id else e for e in catalog.entities)
        )
        return data["hp"]

    def hit(attacker, target):
        if attacker == "hero":
            weapon = owned(state["weapon"])["kind"] if state["weapon"] else "dagger"
            task = "ranged" if weapon in ("longbow", "crossbow") else "melee"
            ability, modifier = bonus(state, char, task)
            damage_modifier = ability_modifier(getattr(char, ability))
            modifier += int(("marksman" if task == "ranged" else "duelist") in state["talents"])
            if task == "ranged":
                arrow = next(
                    (i for i in state["items"] if i["kind"] == "arrow" and i["owner"] == "hero"),
                    None,
                )
                if not arrow:
                    raise ValueError("Нет стрел.")
                state["items"].remove(arrow)
        else:
            _, spec = actor(attacker)
            weapon = spec.properties.get("weapon", "dagger")
            if weapon not in WEAPONS:
                weapon = "dagger"
            damage_modifier = ability_modifier(spec.properties.get("strength", 10))
            modifier = damage_modifier + 2
        if target == "hero":
            armour = owned(state["armour"])["kind"] if state["armour"] else "none"
            defence = armour_class(char.dexterity, armour, bool(state["shield"])) + (
                2 if command == "dodge" else 0
            )
        else:
            _, spec = actor(target)
            defence = armour_class(spec.properties.get("dexterity", 10))
        value = roll("1d20", "Атака")
        natural = value.total
        success = natural == 20 or natural != 1 and natural + modifier >= defence
        damage = 0
        expression = WEAPONS[weapon][0]
        if success:
            if natural == 20:
                number, side = expression.split("d")
                expression = f"{int(number) * 2}d{side}"
            damage = max(
                0,
                roll(expression, "Урон").total + damage_modifier,
            )
            remaining = hp(target, -damage)
            if remaining == 0 and target != "hero":
                award("defeat:" + target, 50)
        else:
            remaining = (
                world.hp if target == "hero" else (actor(target)[0].state or {}).get("hp", 1)
            )
        row = {
            "actor_id": attacker,
            "target_id": target,
            "hit": success,
            "defeated": remaining == 0,
            "damage": damage,
            "attack_bonus": modifier,
            "total": natural + modifier,
            "defence": defence,
            "resolver_version": VERSION,
        }
        attacks.append(row)
        return (
            f"{char.name if attacker == 'hero' else actor(attacker)[1].name}: "
            f"d20({natural}){modifier:+} = {natural + modifier} против AC {defence}: "
            + ("попадание" if success else "промах")
            + f"; {expression}: {damage} урона"
        )

    if command == "check":
        success, text = check(args["task"], args["dc"])
        text += " → " + ("успех" if success else "неудача")
    elif command in ("wait", "advance"):
        minutes = args.get("minutes")
        if type(minutes) is not int or not 0 <= minutes <= 1440:
            raise ValueError("Ожидание0–1440минут.")
        duration = minutes
        text = f"Прошло {minutes} минут."
    elif command == "encounter":
        enemies = args.get("enemies", [])
        allies = args.get("allies", [])
        if (
            state["battle"]
            or not enemies
            or not 1 <= len(enemies) + len(allies) <= 7
            or len(set(enemies + allies)) != len(enemies + allies)
        ):
            raise ValueError("Неверные участники боя.")
        for id in enemies + allies:
            actor(id)
        for id in allies:
            value, spec = actor(id)
            if (
                spec.properties.get("party_ally") is not True
                or (value.state or {}).get("disposition") != "friendly"
            ):
                raise ValueError("Союзник не согласился.")
        state["battle"] = {
            "order": ["hero", *allies, *enemies],
            "sides": dict(
                hero="party", **{i: "party" for i in allies}, **{i: "enemy" for i in enemies}
            ),
            "round": 1,
        }
        state["active"] = enemies[0]
        text = "Началась общая схватка."
    elif command in ("attack", "recover", "dodge"):
        battle = state["battle"]
        if not battle:
            raise ValueError("Нет активной схватки.")
        if command == "attack":
            target = args.get("target")
            if battle["sides"].get(target) != "enemy":
                raise ValueError("Выберите противника.")
            if state["st"] < 2:
                raise ValueError("Недостаточно ST.")
            text = hit("hero", target)
            if state["weapon"]:
                owned(state["weapon"])["durability"] = max(
                    0, owned(state["weapon"])["durability"] - 1
                )
            state["st"] -= 2
        elif command == "recover":
            state["st"] = min(state["st_cap"], state["st"] + 3)
            text = "Герой переводит дух."
        else:
            if state["st"] < 1:
                raise ValueError("Недостаточно ST.")
            state["st"] -= 1
            text = "Уклонение: +2AC до следующего хода."
    elif command in ("cast", "consume"):
        value = owned(args["item"]) if command == "consume" else None
        spell = (
            args.get("spell")
            if command == "cast"
            else {
                "scroll_light": "light",
                "scroll_heal": "heal",
                "mana": "mana",
                "bandage": "bandage",
            }.get(value["kind"])
        )
        target = args.get("target", "hero")
        if target != "hero":
            actor(target)
        if spell not in ("light", "heal", "bolt", "mana", "bandage"):
            raise ValueError("Неподдерживаемый эффект.")
        if command == "cast" and (
            spell not in state["spells"] or state["mp"] < (3 if spell in ("heal", "bolt") else 1)
        ):
            raise ValueError("Заклинание не изучено или недостаточно MP.")
        if spell == "bolt":
            if target == "hero":
                raise ValueError("Выберите противника.")
            value_roll = roll("1d20", "Магическая атака")
            target_entity, target_spec = actor(target)
            defence = armour_class(target_spec.properties.get("dexterity", 10))
            total = (
                value_roll.total + ability_modifier(char.intelligence) + proficiency(state["xp"])
            )
            hit_spell = value_roll.total == 20 or value_roll.total != 1 and total >= defence
            damage = (
                roll("2d6" if value_roll.total == 20 else "1d6", "Магический урон").total
                if hit_spell
                else 0
            )
            if damage:
                remaining = hp(target, -damage)
                if remaining == 0:
                    award("defeat:" + target, 50)
            text = (
                f"Разряд: d20({value_roll.total}), итог {total} против AC {defence}, урон {damage}."
            )
        elif spell == "mana":
            if state["mp"] >= state["mp_cap"]:
                raise ValueError("Мана полна.")
            state["mp"] = min(state["mp_cap"], state["mp"] + 6)
            text = "Восстановлено до6MP."
        elif spell in ("heal", "bandage"):
            amount = roll("1d8" if spell == "heal" else "1d4", "Лечение").total + int(
                "healer" in state["talents"]
            )
            if target == "hero" and world.hp == world.max_hp:
                raise ValueError("Здоровье полное.")
            hp(target, amount)
            text = f"Восстановление HP: {amount}."
        else:
            state["effects"].append({"kind": "light", "until": state["minute"] + 60})
            text = "Подтверждён путеводный свет,60минут."
        if command == "cast":
            state["mp"] -= 3 if spell in ("heal", "bolt") else 1
        else:
            state["items"].remove(value)
    elif command in ("manufacture", "repair", "gather"):
        if state["battle"]:
            raise ValueError("Сначала завершите схватку.")
        if not any(
            i["kind"] == "tools" and i["owner"] == "hero" and i["durability"] > 0
            for i in state["items"]
        ):
            raise ValueError("Нужны исправные инструменты.")
        if command == "gather":
            kind = args["material"]
            quantity = args["quantity"]
            if (
                kind not in ("iron", "wood", "herb")
                or type(quantity) is not int
                or not 1 <= quantity <= 10
            ):
                raise ValueError("Неверный материал/количество.")
            population(state, catalog, scene)
            node = state["living_world"]["nodes"][scene.current]
            if node[kind] < quantity:
                raise ValueError("Запас исчерпан.")
            if roll("1d100", "Поиск сырья").total > 90:
                quantity = 0
            node[kind] -= quantity
            for _ in range(quantity):
                state["items"].append(
                    item(f"crafted_{context['turn']}_{len(state['items'])}", kind)
                )
            text = f"Материала добыто: {quantity}."
            duration = 10 * quantity
        elif command == "repair":
            value = owned(args["item"])
            if value["durability"] >= 20:
                raise ValueError("Ремонт не нужен.")
            success, text = check("repair", 10)
            if success:
                value["durability"] = min(20, value["durability"] + 5)
            duration = 10
        else:
            recipe = args.get("recipe")
            if recipe not in RECIPES:
                raise ValueError("Нет подтверждённого рецепта.")
            materials, task, dc = RECIPES[recipe]
            selected = []
            for kind, amount in materials.items():
                available = [
                    i for i in state["items"] if i["kind"] == kind and i["owner"] == "hero"
                ]
                if len(available) < amount:
                    raise ValueError("Недостаточно материала: " + kind)
                selected += available[:amount]
            success, text = check(task, dc)
            state["items"] = [i for i in state["items"] if i not in selected]
            if success:
                state["items"].append(item(f"crafted_{context['turn']}", recipe))
                award("recipe:" + recipe, 10)
                text += " → изделие создано."
            else:
                text += " → материал израсходован, изделие не создано."
            duration = 30
    elif command in ("buy", "sell", "trade_world"):
        if state["battle"]:
            raise ValueError("Торговля в бою недоступна.")
        merchant, spec = actor(args["merchant"])
        if spec.properties.get("can_trade") is not True and spec.properties.get("class") not in (
            "merchant",
            "trader",
            "shopkeeper",
        ):
            raise ValueError("Участник не торгует.")
        operation = args.get("operation", command)
        if args.get("quantity", 1) != 1:
            raise ValueError("Экземпляр передаётся по одному.")
        if operation == "buy":
            value = next((e for e in catalog.entities if e.id == args["item"]), None)
            if not value or value.owner_id != merchant.id or value.quantity < 1:
                raise ValueError("Товара нет у продавца.")
            definition = next(d for d in catalog.definitions if d.id == value.definition_id)
            price = definition.price_cp
            if price is None or state["copper"] < price:
                raise ValueError("Цена не подтверждена или недостаточно денег.")
            source_id = value.id
            remainder = None
            source_thing = next(t for t in scene.things if t.id == source_id)
            if value.quantity > 1:
                new_id = f"purchase_{context['turn']}"
                if any(e.id == new_id for e in catalog.entities):
                    raise ValueError("Совпадение ID покупки.")
                remainder = replace(value, quantity=value.quantity - 1)
                value = replace(value, id=new_id, quantity=1)
            state["copper"] -= price
            kind = definition.properties.get(
                "unified_kind", definition.properties.get("weapon", "miscellaneous")
            )
            if kind not in ITEMS and kind not in WEAPONS:
                kind = "miscellaneous"
            previous_gear = next((i for i in state["items"] if i["id"] == value.id), None)
            state["items"] = [i for i in state["items"] if i["id"] != value.id]
            state["items"].append(
                {
                    "id": value.id,
                    "kind": kind,
                    "name": definition.name,
                    "owner": "hero",
                    "durability": previous_gear["durability"] if previous_gear else 20,
                    "price_cp": price,
                    "quality": 1,
                    "source": value.id,
                }
            )
            value = replace(value, owner_id="hero", parent_id="hero")
            wallet = dict(merchant.state or {})
            wallet["gold_cp"] = wallet.get("gold_cp", 0) + price
        elif operation == "sell":
            gear = owned(args["item"])
            price = gear["price_cp"] // 2
            wallet = dict(merchant.state or {})
            if wallet.get("gold_cp", 0) < price:
                raise ValueError("У продавца недостаточно средств.")
            if gear["id"] in (state["weapon"], state["armour"], state["shield"]):
                raise ValueError("Сначала снимите экипировку.")
            wallet["gold_cp"] -= price
            state["copper"] += price
            gear["owner"] = merchant.id
            value = None
        else:
            raise ValueError("Неизвестная операция торговли.")
        updated = replace(merchant, state=wallet)
        entries = {e.id: e for e in catalog.entities}
        entries[merchant.id] = updated
        if value:
            if remainder:
                entries[source_id] = remainder
            else:
                entries.pop(source_id, None)
            entries[value.id] = value
            things = {t.id: t for t in scene.things}
            if remainder:
                things[source_id] = replace(source_thing, quantity=remainder.quantity)
            else:
                things.pop(source_id, None)
            things[value.id] = replace(
                source_thing, id=value.id, quantity=1, holder="hero", owner="hero"
            )
            scene = replace(scene, things=tuple(things.values()))
        catalog = replace(catalog, entities=tuple(entries.values()))
        text = f"Сделка подтверждена: {price} медных."
        duration = 5
    elif command == "equip":
        value = owned(args["item"])
        kind = value["kind"]
        slot = (
            "weapon"
            if kind in WEAPONS
            else "shield"
            if kind == "shield"
            else "armour"
            if kind == "leather"
            else ""
        )
        if not slot:
            raise ValueError("Предмет не экипируется.")
        if slot == "shield" and state["weapon"] and WEAPONS[owned(state["weapon"])["kind"]][1] == 2:
            raise ValueError("Оружие двуручное.")
        if slot == "weapon" and WEAPONS[kind][1] == 2:
            state["shield"] = ""
        state[slot] = value["id"]
        text = "Экипировано: " + value["name"]
    elif command == "rest":
        if state["battle"]:
            raise ValueError("Отдых в бою невозможен.")
        limits = caps(state, char)
        world = replace(world, hp=world.max_hp)
        state.update(mp=limits["mp"], st=limits["st"])
        duration = 480
        text = "Отдых завершён."
    elif command == "raise":
        key = args["ability"]
        available = 2 * sum(level(state["xp"]) >= n for n in (4, 8, 12, 16, 20)) - sum(
            state["ability_increases"].values()
        )
        if key not in asdict(char) or key == "name" or not available or getattr(char, key) >= 20:
            raise ValueError("Повышение недоступно.")
        state["ability_increases"][key] = state["ability_increases"].get(key, 0) + 1
        text = "Характеристика повышена."
        char = replace(char, **{key: getattr(char, key) + 1})
    elif command == "talent":
        key = args["talent"]
        allowed = 1 + sum(level(state["xp"]) >= n for n in (5, 10, 15, 20))
        if (
            key not in talents(state["identity"]["class_id"])
            or key in state["talents"]
            or len(state["talents"]) >= allowed
        ):
            raise ValueError("Талант недоступен.")
        state["talents"].append(key)
        text = "Получен талант: " + TALENTS[key][0]
    else:
        raise ValueError("Действие не поддержано едиными правилами: " + str(command))
    # State items reference the same physical source, never a second copy of it.
    # A sold/consumed source must stop being carried in both world read models.
    if catalog:
        bound = touched_sources | {
            i["source"] for i in original["items"] + state["items"] if i.get("source")
        }
        current = {i["source"]: i for i in state["items"] if i.get("source")}
        entries = {e.id: e for e in catalog.entities}
        things = {t.id: t for t in scene.things}
        for source_id in bound:
            gear = current.get(source_id)
            if gear is None:
                entries.pop(source_id, None)
                things.pop(source_id, None)
            elif source_id in entries and source_id in things:
                owner = gear["owner"]
                entries[source_id] = replace(entries[source_id], owner_id=owner, parent_id=owner)
                things[source_id] = replace(things[source_id], owner=owner, holder=owner)
        catalog = replace(catalog, entities=tuple(entries.values()))
        scene = replace(scene, things=tuple(things.values()))
    if state["battle"] and command != "encounter":
        battle = state["battle"]
        for id in battle["order"][1:]:
            if world.hp <= 0:
                break
            try:
                actor(id)
            except ValueError:
                continue
            if battle["sides"][id] == "party":
                target = next(
                    (
                        i
                        for i in battle["order"]
                        if battle["sides"][i] == "enemy"
                        and next(
                            (
                                e
                                for e in catalog.entities
                                if e.id == i and (e.state or {}).get("hp", 1) > 0
                            ),
                            None,
                        )
                    ),
                    None,
                )
            else:
                target = "hero"
            if target:
                text += "\n" + hit(id, target)
        alive = [
            i
            for i in battle["order"]
            if battle["sides"][i] == "enemy"
            and next(
                (e for e in catalog.entities if e.id == i and (e.state or {}).get("hp", 1) > 0),
                None,
            )
        ]
        battle["round"] += 1
        if not alive or world.hp == 0:
            state.update(last_battle=battle, battle=None, active=None)
        else:
            state["active"] = alive[0]
    state["minute"] += duration
    factions(state, catalog, scene)
    state, scene, _ = simulate(state, catalog, scene)
    state, catalog, scene, _ = advance(state, catalog, scene)
    limits = caps(state, char)
    world = replace(world, max_hp=limits["hp"], hp=min(world.hp, limits["hp"]))
    state.update(mp_cap=limits["mp"], st_cap=limits["st"])
    return {
        "state": state,
        "world": asdict(world),
        "combat": context["combat"],
        "scene": scene.to_dict(),
        "catalog": catalog.to_dict() if catalog else None,
        "text": text,
        "rolls": rolls,
        "attacks": attacks,
        "battle_events": events,
    }
