"""Small versioned playable homebrew catalog; deterministic transactions, no narrator authority."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain.character import ABILITY_NAMES, Character, ability_modifier
from rpg_vkr.domain.combat import ACTORS, CombatState
from rpg_vkr.domain.d20_combat import ARMOUR, WEAPONS, Combatant, resolve_attack
from rpg_vkr.domain.d20_progression import RULESET_ID, D20Progress
from rpg_vkr.domain.interactions import InteractiveWorld, identifier, label
from rpg_vkr.domain.world import WorldState

VERSION = "gameplay-v3-playable-1"
CATALOG_VERSION = "gameplay-catalog-1"
SHOP_STOCK = (
    tuple(WEAPONS) + tuple(k for k in ARMOUR if k != "none") + ("shield", "herb", "iron", "cloth")
)
SPECIES = {
    "human": "Человек",
    "elf": "Эльф",
    "dwarf": "Дворф",
    "orc": "Орк",
    "halfling": "Полурослик",
}
PROFILES = {
    "warrior": "Воин",
    "ranger": "Следопыт",
    "mage": "Маг",
    "healer": "Целитель",
    "artisan": "Ремесленник",
    "free": "Свободный",
}
# Six profiles are presets and permissions, never a replacement of stored legacy class IDs.
SPELLS = {
    "spark": ("Искра", 1, 3, "attack", "1d6", 12, 0),
    "mend": ("Исцеление", 1, 4, "heal", "1d6", 0, 1),
    "ward": ("Защита", 1, 3, "ward", "", 0, 0),
    "light": ("Свет", 1, 1, "light", "", 0, 0),
    "flame": ("Пламя", 2, 7, "attack", "2d6", 18, 1),
    "restore": ("Восстановление", 2, 7, "heal", "2d6", 0, 2),
}
TALENTS = {
    "accuracy": "Точный удар: +1 к атакующей характеристике (до 20)",
    "scholar": "Учёный: +1 к магической характеристике (до 20)",
    "medic": "Лекарь: +2 к восстановлению HP",
}
ITEM_NAMES = {
    "dagger": "Кинжал",
    "sword": "Меч",
    "short_sword": "Короткий меч",
    "greatsword": "Двуручный меч",
    "axe": "Топор",
    "longbow": "Длинный лук",
    "crossbow": "Арбалет",
    "leather": "Кожаный доспех",
    "reinforced_leather": "Укреплённая кожа",
    "mail": "Кольчуга",
    "plate": "Латы",
    "shield": "Щит",
    "cloth": "Ткань",
    "herb": "Лечебная трава",
    "iron": "Железо",
    "tools": "Полевой верстак",
    "focus": "Магический фокус",
    "bandage": "Бинт",
}
PRICES = {
    "dagger": 150,
    "sword": 500,
    "short_sword": 350,
    "greatsword": 900,
    "axe": 700,
    "longbow": 600,
    "crossbow": 700,
    "leather": 400,
    "reinforced_leather": 700,
    "mail": 1600,
    "plate": 3000,
    "shield": 300,
    "cloth": 30,
    "herb": 40,
    "iron": 60,
    "tools": 200,
    "focus": 200,
}
RECIPES = {
    "dagger": ("smithing", {"iron": 2}, 30, 12),
    "bandage": ("repair", {"cloth": 1, "herb": 1}, 10, 10),
}


def initial(identity, character):
    if (
        not isinstance(identity, dict)
        or not {
            "species",
            "profile",
            "background",
            "appearance",
            "age",
        }
        <= set(identity)
        or set(identity)
        - {"species", "profile", "background", "appearance", "age", "talent", "skills"}
    ):
        raise ValueError("Нужны личность, происхождение и профиль героя.")
    if identity["species"] not in SPECIES or identity["profile"] not in PROFILES:
        raise ValueError("Неизвестный вид или профиль.")
    if type(identity["age"]) is not int or not 18 <= identity["age"] <= 1000:
        raise ValueError("Возраст героя: 18–1000.")
    for key in ("background", "appearance"):
        label(identity[key], 400)
    talent = identity.get("talent", "")
    if talent and talent not in TALENTS:
        raise ValueError("Неизвестный начальный талант.")
    skills = identity.get("skills", {})
    if not isinstance(skills, dict):
        raise ValueError("Неверный черновик навыков.")
    draft = D20Progress()
    for skill, rank in skills.items():
        if type(rank) is not int or not 0 <= rank <= 2:
            raise ValueError("Начальный ранг навыка: 0–2.")
        for n in range(rank):
            draft = draft.train(skill, f"creation:{skill}:{n}")
    items = []
    weapon = {"warrior": "sword", "ranger": "short_sword"}.get(identity["profile"], "dagger")
    for kind in (
        weapon,
        "leather",
        "shield",
        "tools",
        "focus",
        "cloth",
        "cloth",
        "herb",
        "herb",
        "iron",
        "iron",
    ):
        items.append(item(f"kit_{len(items)}", kind))
    magic = identity["profile"] in {"mage", "healer"}
    maximum = max(4, 12 + 4 * ability_modifier(character.intelligence)) if magic else 0
    return {
        "version": VERSION,
        "ruleset_id": RULESET_ID,
        "catalog_version": CATALOG_VERSION,
        "identity": deepcopy(identity),
        "items": items,
        "weapon": "kit_0",
        "armour": "kit_1",
        "shield": "",
        "copper": 0,
        "minute": 480,
        "mp": maximum,
        "mp_cap": maximum,
        "spells": [],
        "talents": [talent] if talent else [],
        "attributes": [],
        "effects": [],
        "active": "",
        "distance": 1,
        "round": 0,
        "initiative": [],
        "npc": {},
        "factions": {},
        "victories": [],
        "stocked": [],
    }


def stock_id(merchant, kind):
    from hashlib import sha256

    value = f"shop_{merchant}_{kind}"
    return (
        value if len(value) <= 64 else f"shop_{sha256(merchant.encode()).hexdigest()[:16]}_{kind}"
    )


def ensure_names(state, catalog):
    if catalog and {i["id"] for i in state["items"]} & {
        v.id for v in (*catalog.entities, *catalog.definitions)
    }:
        raise ValueError("ID нового предмета совпал с существующим объектом мира.")


def item(id, kind, owner="hero"):
    identifier(id)
    if kind not in PRICES:
        raise ValueError("Неизвестный тип предмета.")
    return {"id": id, "kind": kind, "owner": owner, "durability": 20, "quality": 1}


def owned(state, id):
    value = next((i for i in state["items"] if i["id"] == id and i["owner"] == "hero"), None)
    if value is None:
        raise ValueError("Предмет не принадлежит герою или недоступен.")
    return value


def equipped(state, slot, fallback):
    id = state[slot]
    if not id:
        return fallback
    value = owned(state, id)
    if value["durability"] <= 0 and slot != "weapon":
        return fallback
    return value["kind"]


def effective_character(state, character):
    scores = {a: character.score(a) + state["attributes"].count(a) for a in ABILITY_NAMES}
    if "accuracy" in state["talents"]:
        scores["strength"] = min(20, scores["strength"] + 1)
    if "scholar" in state["talents"]:
        scores["intelligence"] = min(20, scores["intelligence"] + 1)
    return replace(character, **scores)


def hero_combatant(state, world, character, progress):
    character = effective_character(state, character)
    weapon = equipped(state, "weapon", "dagger")
    score = character.dexterity if weapon in {"longbow", "crossbow"} else character.strength
    return Combatant(
        "hero",
        world.hp,
        world.max_hp,
        score,
        character.dexterity,
        weapon,
        progress.rank("acrobatics" if weapon in {"longbow", "crossbow"} else "athletics"),
        equipped(state, "armour", "none"),
        bool(state["shield"] and owned(state, state["shield"])["durability"]),
    )


def available(state, id, definition=None):
    """Only public working hours; no hidden inventories or beliefs enter UI."""
    if definition and "creatures" in definition.categories:
        return True
    hour = state["minute"] // 60 % 24
    merchant = id == "merchant" or bool(
        definition
        and (
            definition.properties.get("can_trade")
            or definition.properties.get("class")
            in {"merchant", "trader", "shopkeeper", "торговец", "купец"}
        )
    )
    return 8 <= hour < 20 if merchant else 6 <= hour < 22


def execute(state, command, args, context, dice):
    """Pure candidate computation. Caller commits all returned values or restores RNG."""
    from rpg_vkr.domain.catalog import Catalog, seed_catalog
    from rpg_vkr.domain.resources import reconcile

    if not isinstance(args, dict) or any(
        not isinstance(v, (str, int)) or type(v) is bool for v in args.values()
    ):
        raise ValueError("Неверные параметры команды.")
    signatures = {
        "equip": {"item"},
        "unequip": {"slot"},
        "attack": {"target", "lethal"},
        "dodge": set(),
        "retreat": set(),
        "move": {"distance"},
        "bandage": set(),
        "learn": {"spell"},
        "cast": {"spell", "target"},
        "talent": {"talent"},
        "attribute": {"ability"},
        "craft": {"recipe"},
        "prepare": {"item"},
        "repair": {"item"},
        "buy": {"merchant", "item"},
        "sell": {"merchant", "item"},
        "wait": {"minutes"},
        "advance": {"minutes"},
        "rest": set(),
        "tell": {"target", "event"},
    }
    if (
        not isinstance(command, str)
        or command not in signatures
        or set(args) != signatures[command]
    ):
        raise ValueError("Неизвестная команда или лишние параметры.")
    for key, value in args.items():
        if key in {"minutes", "distance", "lethal"}:
            if type(value) is not int:
                raise ValueError("Нужен целый числовой параметр.")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError("Нужен непустой идентификатор.")
    state = deepcopy(state)
    if (
        state["version"] != VERSION
        or state["ruleset_id"] != RULESET_ID
        or state["catalog_version"] != CATALOG_VERSION
    ):
        raise ValueError("Неизвестная версия игровых правил.")
    world = WorldState.from_dict(context["world"])
    before_world = world
    character = Character.from_dict(context["character"])
    combat = CombatState.from_dict(context["combat"])
    scene = InteractiveWorld.from_dict(context["scene"])
    catalog = Catalog.from_dict(context["catalog"]) if context["catalog"] else seed_catalog()
    progress = D20Progress.from_dict(context["progress"])
    ensure_names(state, catalog)
    if (world.hp <= 0 or combat.active) and command != "advance":
        raise ValueError("Действие недоступно после выбытия или в прежней схватке.")
    if state["active"] and command not in {
        "attack",
        "dodge",
        "retreat",
        "move",
        "bandage",
        "cast",
        "advance",
    }:
        raise ValueError("Завершите бой: доступны атака, магия, манёвр и бинт.")
    hero = effective_character(state, character)
    log, outcomes, rolls = [], [], []
    duration = 0

    class TrackedDice:
        def checkpoint(self):
            return dice.checkpoint()

        def restore(self, value):
            dice.restore(value)

        def roll_d20(self):
            value = dice.roll_d20()
            rolls.append(asdict(value))
            return value

        def roll(self, expression, *, reason):
            start = dice.checkpoint()[1]
            value = dice.roll(expression, reason=reason)
            rolls.extend(
                {"index": start + i + 1, "value": v} for i, v in enumerate(value.individual_rolls)
            )
            return value

    rng = TrackedDice()

    def target(id):
        identifier(id)
        ref = next((a for a in scene.actor_refs if a.id == id and a.place == scene.current), None)
        entity = next((e for e in catalog.entities if e.id == id), None)
        definition = next(
            (d for d in catalog.definitions if entity and d.id == entity.definition_id), None
        )
        if not ref or (id != state["active"] and not available(state, id, definition)):
            raise ValueError("Цель отсутствует или недоступна по расписанию.")
        if id in ACTORS:
            actor = combat.actor(id)
            hp, maximum = actor.hp, ACTORS[id][2]
        elif entity and definition and definition.kind == "actor":
            maximum = definition.properties["hp_max"]
            hp = (entity.state or {}).get("hp", maximum)
        else:
            raise ValueError("Нет проверенной карточки участника.")
        if hp <= 0:
            raise ValueError("Цель уже повержена.")
        props = definition.properties if definition else {}

        def score(key, fallback=10):
            value = props.get(key, fallback)
            return value if type(value) is int and 1 <= value <= 30 else fallback

        weapon = props.get("weapon", "dagger")
        armour = props.get("armour", "none")
        if weapon not in WEAPONS or armour not in ARMOUR:
            raise ValueError("Снаряжение NPC не входит в каталог правил.")
        return (
            Combatant(
                id, hp, maximum, score("strength", 12), score("dexterity"), weapon, 0, armour, False
            ),
            entity,
            definition,
        )

    def change_target(id, hp, lethal=False):
        nonlocal catalog, combat
        if id in ACTORS:
            old = combat.actor(id)
            combat = combat.update(replace(old, hp=hp, disposition="hostile"))
        entity = next((e for e in catalog.entities if e.id == id), None)
        if entity:
            values = (entity.state or {}) | {"hp": hp, "disposition": "hostile"}
            if hp == 0:
                values["life"] = "dead" if lethal else "unconscious"
            changed = replace(entity, state=values)
            catalog = replace(
                catalog, entities=tuple(changed if e.id == id else e for e in catalog.entities)
            )
        if hp == 0:
            if id not in state["victories"]:
                state["victories"].append(id)
            for ref in scene.actor_refs:
                if ref.id == id or ref.place != scene.current:
                    continue
                observer = next((e for e in catalog.entities if e.id == ref.id), None)
                definition = next(
                    (d for d in catalog.definitions if observer and d.id == observer.definition_id),
                    None,
                )
                living = (
                    combat.actor(ref.id).hp > 0
                    if ref.id in ACTORS
                    else bool(
                        observer
                        and (observer.state or {}).get("hp", definition.properties["hp_max"]) > 0
                    )
                )
                if not living or not available(state, ref.id, definition):
                    continue
                witness = state["npc"].setdefault(ref.id, {"heard": [], "source": "hero"})
                knowledge = witness.setdefault("knowledge", [])
                if not any(k["event"] == id and k["kind"] == "personally_known" for k in knowledge):
                    knowledge.append(
                        {
                            "event": id,
                            "kind": "personally_known",
                            "source": f"turn_{context['turn']}",
                            "confidence": 100,
                        }
                    )
            state["active"] = ""
            state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
            log.append("Цель погибла." if lethal else "Цель повержена, нелетальный исход.")

    def hit(actor, defender, **modes):
        result = resolve_attack(actor, defender, rng, **modes)
        outcomes.append(asdict(result))
        log.append(
            f"{actor.id}: d20 {list(result.hit_rolls)} {result.attack_bonus:+d} "
            f"= {result.total} против AC {result.defence}; "
            + (
                f"урон {result.damage_roll.expression} "
                f"{list(result.damage_roll.individual_rolls)} + модификатор = {result.damage}."
                if result.hit
                else "промах."
            )
        )
        return result

    def counter(*, disadvantage=False):
        nonlocal world
        if not state["active"] or world.hp == 0:
            return
        enemy, _, _ = target(state["active"])
        reach = 30 if enemy.weapon in {"longbow", "crossbow"} else 1
        if state["distance"] > reach:
            log.append("Противник вне дальности ответной атаки.")
            return
        defender = hero_combatant(state, world, character, progress)
        # Ward is a timed defensive effect, implemented by disadvantage (not flat AC stacking).
        protected = any(e["kind"] == "ward" for e in state["effects"])
        result = hit(enemy, defender, disadvantage=disadvantage or protected)
        world = replace(world, hp=result.hp_after)
        if world.hp == 0:
            state["active"] = ""
            log.append("Герой выведен из боя. Загрузите сохранение.")
            state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
        elif result.damage and protected:
            concentration = rng.roll_d20().value + ability_modifier(hero.constitution)
            if concentration < max(10, result.damage // 2):
                state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
                log.append("Концентрация потеряна.")

    def begin_encounter(enemy):
        nonlocal world
        world = replace(world, trading=False)
        if state["active"]:
            return False
        state["active"] = enemy.id
        state["initiative"] = [
            rng.roll_d20().value + ability_modifier(hero.dexterity),
            rng.roll_d20().value + ability_modifier(enemy.dexterity),
        ]
        log.append(f"Инициатива герой/NPC: {state['initiative']} (при равенстве герой первый).")
        faster = state["initiative"][1] > state["initiative"][0]
        if faster:
            counter()
        return faster

    if command == "equip":
        value = owned(state, args["item"])
        kind = value["kind"]
        if value["durability"] <= 0:
            raise ValueError("Предмет сломан.")
        slot = (
            "weapon"
            if kind in WEAPONS
            else "armour"
            if kind in ARMOUR
            else "shield"
            if kind == "shield"
            else ""
        )
        if not slot:
            raise ValueError("Этот предмет не экипируется.")
        if slot == "shield" and WEAPONS[equipped(state, "weapon", "dagger")][1] == 2:
            raise ValueError("Сначала снимите двуручное оружие.")
        if slot == "weapon" and WEAPONS[kind][1] == 2 and state["shield"]:
            raise ValueError("Сначала снимите щит.")
        state[slot] = value["id"]
        log.append("Экипировано: " + ITEM_NAMES[kind])
        duration = 1
    elif command == "unequip":
        if args["slot"] not in {"weapon", "armour", "shield"}:
            raise ValueError("Неизвестный слот.")
        if args["slot"] == "weapon":
            raise ValueError("Для боя выберите другое имеющееся оружие.")
        state[args["slot"]] = ""
        duration = 1
        log.append("Предмет снят.")
    elif command in {"attack", "dodge", "move", "retreat", "bandage"}:
        if command == "attack":
            if type(args["lethal"]) is not int or args["lethal"] not in (0, 1):
                raise ValueError("Нужен явный режим летальности 0/1.")
            id = args["target"]
            if state["active"] and id != state["active"]:
                raise ValueError("Сначала завершите текущий бой.")
            enemy, _, _ = target(id)
            if not state["weapon"] or owned(state, state["weapon"])["durability"] <= 0:
                raise ValueError("Выбранное оружие сломано. Отступите и почините его.")
            attacker = hero_combatant(state, world, character, progress)
            maximum_range = 30 if attacker.weapon in {"longbow", "crossbow"} else 1
            if state["distance"] > maximum_range:
                raise ValueError("Цель вне дальности оружия. Сблизьтесь.")
            first_counter = begin_encounter(enemy)
            if world.hp:
                result = hit(attacker, enemy, lethal=bool(args["lethal"]))
                change_target(id, result.hp_after, bool(args["lethal"]))
                value = owned(state, state["weapon"])
                value["durability"] = max(0, value["durability"] - 1)
                if not first_counter:
                    counter()
        else:
            if not state["active"]:
                raise ValueError("Нет активной схватки.")
            if command == "dodge":
                log.append("Уклонение: ответная атака с помехой.")
                counter(disadvantage=True)
            elif command == "retreat":
                state["active"] = ""
                state["distance"] = 1
                state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
                log.append("Безопасный выход из боя: действие потрачено, без ответного удара.")
            elif command == "move":
                if (
                    type(args["distance"]) is not int
                    or not 1 <= args["distance"] <= 30
                    or abs(args["distance"] - state["distance"]) > 6
                ):
                    raise ValueError("За действие можно изменить дистанцию не более чем на 6 м.")
                state["distance"] = args["distance"]
                log.append(f"Дистанция {state['distance']} м; действие потрачено.")
                if state["distance"] <= 1:
                    counter()
            else:
                if world.bandages <= 0 or world.hp == world.max_hp:
                    raise ValueError("Нет бинта или здоровье полное.")
                world = replace(
                    world, hp=min(world.max_hp, world.hp + 4), bandages=world.bandages - 1
                )
                log.append("Бинт: до 4 HP.")
                counter()
        state["round"] += 1
        duration = 1
    elif command == "learn":
        key = args["spell"]
        if key not in SPELLS or key in state["spells"]:
            raise ValueError("Заклинание неизвестно или уже изучено.")
        if progress.rank("arcana") < SPELLS[key][1] or (SPELLS[key][1] == 2 and progress.level < 5):
            raise ValueError("Нужны ранг Теории магии не ниже круга; II круг с уровня 5.")
        if not any(i["kind"] == "focus" and i["owner"] == "hero" for i in state["items"]):
            raise ValueError("Нужен магический фокус.")
        state["spells"].append(key)
        maximum = max(4, 12 + 4 * ability_modifier(hero.intelligence) + 4 * (progress.level - 1))
        state["mp_cap"] = maximum
        # Learning is not a refill. Noncasters obtain MP by a real rest.
        log.append("Изучено: " + SPELLS[key][0])
        duration = 60
    elif command == "cast":
        key = args["spell"]
        if key not in state["spells"] or key not in SPELLS:
            raise ValueError("Сначала изучите заклинание.")
        name, circle, cost, effect, expression, reach, components = SPELLS[key]
        if state["mp"] < cost:
            raise ValueError("Недостаточно MP.")
        if not any(
            i["kind"] == "focus" and i["owner"] == "hero" and i["durability"]
            for i in state["items"]
        ):
            raise ValueError("Нет исправного магического фокуса.")
        herbs = [i for i in state["items"] if i["kind"] == "herb" and i["owner"] == "hero"]
        if len(herbs) < components:
            raise ValueError("Недостаточно компонентов: лечебная трава.")
        if effect != "attack" and args["target"] != "hero":
            raise ValueError("Это заклинание применяется к герою.")
        if effect == "heal" and world.hp == world.max_hp:
            raise ValueError("Здоровье уже полное.")
        enemy = None
        if effect == "attack":
            enemy, _, _ = target(args["target"])
            if state["active"] not in {"", enemy.id} or state["distance"] > reach:
                raise ValueError("Недопустимая цель или дальность.")
        if effect == "ward" and any(e["kind"] == "ward" for e in state["effects"]):
            raise ValueError("Защита уже действует.")
        first_counter = begin_encounter(enemy) if enemy else False
        if world.hp:
            state["mp"] -= cost
            for value in herbs[:components]:
                state["items"].remove(value)
            log.append(f"{name}: потрачено {cost} MP.")
            if effect == "attack":
                dc = 8 + ability_modifier(hero.intelligence) + 2 * progress.rank("arcana")
                save = rng.roll_d20().value + ability_modifier(enemy.dexterity)
                damage_roll = rng.roll(expression, reason="Урон заклинания")
                damage = damage_roll.total if save < dc else 0
                log.append(
                    f"Спасбросок {save} против DC {dc}; "
                    f"{expression} {list(damage_roll.individual_rolls)}, урон {damage}."
                )
                state["active"] = enemy.id
                change_target(enemy.id, max(0, enemy.hp - damage))
            elif effect == "heal":
                result = rng.roll(expression, reason="Лечение")
                healing = max(
                    0,
                    result.total
                    + ability_modifier(hero.intelligence)
                    + (2 if "medic" in state["talents"] else 0),
                )
                restored = min(healing, world.max_hp - world.hp)
                world = replace(world, hp=world.hp + restored)
                log.append(f"Восстановлено {restored} HP.")
            else:
                state["effects"] = [e for e in state["effects"] if e["kind"] != effect]
                state["effects"].append(
                    {"kind": effect, "expires": state["minute"] + (10 if effect == "ward" else 60)}
                )
                log.append(
                    "Защита даёт помеху атакующему и требует концентрации."
                    if effect == "ward"
                    else "Свет действует 60 минут."
                )
            if not first_counter:
                counter()
        else:
            log.append("Герой выведен из боя до заклинания; MP и компоненты не потрачены.")
        state["round"] += bool(state["active"])
        duration = 1
    elif command == "talent":
        key = args["talent"]
        if (
            key not in TALENTS
            or key in state["talents"]
            or len(state["talents"]) >= progress.talent_rewards
        ):
            raise ValueError("Талант неизвестен, уже получен или нет награды.")
        state["talents"].append(key)
        log.append("Получен талант: " + TALENTS[key])
    elif command == "attribute":
        key = args["ability"]
        if (
            key not in ABILITY_NAMES
            or len(state["attributes"]) >= progress.attribute_rewards
            or hero.score(key) >= 20
        ):
            raise ValueError("Нет повышения характеристики или достигнут предел 20.")
        state["attributes"].append(key)
        log.append("Повышение: " + ABILITY_NAMES[key] + " +1.")
    elif command == "prepare":
        from rpg_vkr.domain.resources import accessible

        thing = next((t for t in scene.things if t.id == args["item"]), None)
        entity = next((e for e in catalog.entities if e.id == args["item"]), None)
        kinds = {
            "mat_iron": "iron",
            "mat_linen": "cloth",
            "mat_wool": "cloth",
            "mat_silk": "cloth",
            "type_healing_herb": "herb",
        }
        if (
            not thing
            or not entity
            or thing.owner not in {"", "hero"}
            or not accessible(scene, thing, catalog)
            or entity.definition_id not in kinds
            or thing.resource
            or thing.container
        ):
            raise ValueError("Нужен доступный собственный материал из каталога в инвентаре.")
        kind = kinds[entity.definition_id]
        if thing.quantity == 1:
            scene = replace(scene, things=tuple(t for t in scene.things if t.id != thing.id))
            catalog = replace(
                catalog, entities=tuple(e for e in catalog.entities if e.id != entity.id)
            )
        else:
            scene = replace(
                scene,
                things=tuple(
                    replace(t, quantity=t.quantity - 1) if t.id == thing.id else t
                    for t in scene.things
                ),
            )
            catalog = replace(
                catalog,
                entities=tuple(
                    replace(e, quantity=thing.quantity - 1, owner_id="hero", parent_id=thing.holder)
                    if e.id == entity.id
                    else e
                    for e in catalog.entities
                ),
            )
        state["items"].append(item(f"prepared_{context['turn']}", kind))
        duration = 1
        log.append(
            "Материал подготовлен: " + ITEM_NAMES[kind] + ". Исходная единица израсходована."
        )
    elif command in {"craft", "repair"}:
        if not any(
            i["kind"] == "tools" and i["owner"] == "hero" and i["durability"]
            for i in state["items"]
        ):
            raise ValueError("Нужен исправный полевой верстак.")
        if command == "craft":
            key = args["recipe"]
            if key not in RECIPES:
                raise ValueError("Неизвестный рецепт.")
            skill, needed, duration, dc = RECIPES[key]
        else:
            value = owned(state, args["item"])
            if value["durability"] >= 20 or value["kind"] not in {*WEAPONS, *ARMOUR, "shield"}:
                raise ValueError("Предмет не требует ремонта или не ремонтируется этим набором.")
            key, skill, needed, duration, dc = value["kind"], "repair", {"iron": 1}, 15, 10
        if progress.rank(skill) < 1:
            raise ValueError("Нужен хотя бы первый ранг навыка: " + skill)
        consumed = []
        for kind, quantity in needed.items():
            found = [i for i in state["items"] if i["kind"] == kind and i["owner"] == "hero"][
                :quantity
            ]
            if len(found) < quantity:
                raise ValueError("Недостаточно материала: " + ITEM_NAMES[kind])
            consumed.extend(found)
        roll = rng.roll_d20().value
        total = roll + ability_modifier(hero.intelligence) + 2 * progress.rank(skill)
        for value in consumed:
            state["items"].remove(value)
        success = total >= dc
        if success and command == "craft":
            if key == "bandage":
                world = replace(world, bandages=world.bandages + 1)
            else:
                state["items"].append(item(f"made_{context['turn']}", key))
        elif success:
            owned(state, args["item"])["durability"] = 20
        log.append(
            f"{command}: d20 {roll}, итог {total} против DC {dc}; "
            + ("готово." if success else "неудача; материалы израсходованы.")
            + f" Время {duration} мин."
        )
    elif command in {"buy", "sell"}:
        from rpg_vkr.domain.trade import merchant

        id = args["merchant"]
        _, entity, _ = target(id)
        if id != "merchant":
            entity = merchant(catalog, id)
        elif combat.actor(id).disposition == "hostile":
            raise ValueError("Враждебный торговец недоступен.")
        legacy_shop = entity is None and id == "merchant"
        if not entity and not legacy_shop:
            raise ValueError("У торговца нет подтверждённого кошелька в каталоге.")
        if id not in state["stocked"]:
            for kind in SHOP_STOCK:
                state["items"].append(item(stock_id(id, kind), kind, id))
            state["stocked"].append(id)
        value = next((i for i in state["items"] if i["id"] == args["item"]), None)
        if not value or value["owner"] != (id if command == "buy" else "hero"):
            raise ValueError("Товар не находится у продавца.")
        if value["id"] in [state[s] for s in ("weapon", "armour", "shield")]:
            raise ValueError("Сначала снимите предмет.")
        base = PRICES[value["kind"]] * value["durability"] // 20
        # Daily, bounded market coefficient. Selling is always below buying.
        coefficient = 100 + min(20, state["minute"] // 1440 % 3 * 10)
        price = max(1, (base * coefficient + 99) // 100) if command == "buy" else base // 2
        wallet = (
            world.shop_gold * 100 + state.get("shop_copper", 0)
            if legacy_shop
            else (entity.state or {}).get("gold_cp", 0)
        )
        coins = world.gold * 100 + state["copper"]
        if (
            price <= 0
            or (command == "buy" and coins < price)
            or (command == "sell" and wallet < price)
        ):
            raise ValueError("Недостаточно монет или предмет не имеет цены.")
        delta = -price if command == "buy" else price
        coins += delta
        world = replace(world, gold=coins // 100)
        state["copper"] = coins % 100
        value["owner"] = "hero" if command == "buy" else id
        if legacy_shop:
            world = replace(world, shop_gold=(wallet - delta) // 100)
            state["shop_copper"] = (wallet - delta) % 100
        else:
            changed = replace(entity, state=(entity.state or {}) | {"gold_cp": wallet - delta})
            catalog = replace(
                catalog, entities=tuple(changed if e.id == id else e for e in catalog.entities)
            )
        log.append(
            f"Сделка: {ITEM_NAMES[value['kind']]}, {price} медных; остаток героя {coins} медных."
        )
        duration = 5
    elif command in {"wait", "rest", "advance"}:
        duration = 480 if command == "rest" else args["minutes"]
        if type(duration) is not int or not 1 <= duration <= 10080:
            raise ValueError("Ожидание: 1–10080 минут.")
        if command == "rest":
            state["mp_cap"] = (
                max(4, 12 + 4 * ability_modifier(hero.intelligence) + 4 * (progress.level - 1))
                if state["spells"] or state["mp_cap"]
                else 0
            )
            state["mp"] = state["mp_cap"]
            world = replace(world, hp=world.max_hp)
            log.append("Отдых 8 часов: HP и MP восстановлены.")
        else:
            log.append(f"Прошло {duration} минут.")
    elif command == "tell":
        id = args["target"]
        _, _, definition = target(id)
        if id in {"wolf", "boar"} or definition and "creatures" in definition.categories:
            raise ValueError("У этой цели нет подтверждённого речевого общения.")
        event = args["event"]
        # Only an engine-confirmed victory can be transmitted, not arbitrary facts.
        if event not in state["victories"]:
            raise ValueError("Можно передать только известный подтверждённый исход.")
        npc = state["npc"].setdefault(id, {"heard": [], "source": "hero"})
        if event in npc["heard"] or any(k["event"] == event for k in npc.get("knowledge", [])):
            raise ValueError("Собеседник уже слышал сообщение или видел событие лично.")
        npc["heard"].append(event)
        npc.setdefault("knowledge", []).append(
            {"event": event, "kind": "heard", "source": "hero", "confidence": 50}
        )
        faction = "local_witnesses"
        state["factions"][faction] = min(100, state["factions"].get(faction, 0) + 1)
        log.append(
            "Собеседник услышал сообщение от героя; оно остаётся сообщением, "
            "не личным наблюдением. Репутация местных свидетелей +1."
        )
        duration = 5
    old_day = state["minute"] // 1440
    state["minute"] += duration
    days = state["minute"] // 1440 - old_day
    if days:
        projects = state.setdefault("faction_projects", {"artisans": 0})
        projects["artisans"] += days
        log.append(
            f"Ремесленная община: прошло {days} дней работы; этап проекта {projects['artisans']}."
        )
    # Deterministic schedules only use existing registered locations.
    places = {p.id for p in scene.places}
    refs = []
    for ref in scene.actor_refs:
        entity = next((e for e in catalog.entities if e.id == ref.id), None)
        definition = next(
            (d for d in catalog.definitions if entity and d.id == entity.definition_id), None
        )
        props = definition.properties if definition else {}
        npc = state["npc"].setdefault(ref.id, {"heard": [], "source": "hero"})
        npc.setdefault("work", ref.place)
        home = props.get("home_id", ref.place)
        npc.setdefault("home", home if isinstance(home, str) and home in places else ref.place)
        awake = available(state, ref.id, definition)
        npc["activity"] = "working" if awake else "resting"
        place = npc["work"] if awake or ref.id == state["active"] else npc["home"]
        refs.append(replace(ref, place=place))
    # v1's computed actors become an explicit v2 roster when a schedule moves anyone.
    if any(a.place != b.place for a, b in zip(scene.actor_refs, refs, strict=True)):
        scene = replace(
            scene,
            actors=tuple(refs),
            version="interactive-world-2"
            if scene.version == "interactive-world-1"
            else scene.version,
        )
    state["effects"] = [e for e in state["effects"] if e["expires"] > state["minute"]]
    if not state["active"]:
        state["round"] = 0
        state["distance"] = 1
        state["initiative"] = []
    # Reconcile actual coin/bandage stacks with authoritative legacy counters.
    scene = reconcile(scene, before_world, world, context["turn"], catalog)
    ensure_names(state, catalog)
    return {
        "state": state,
        "world": asdict(world),
        "combat": combat.to_dict(),
        "scene": scene.to_dict(),
        "catalog": catalog.to_dict() if context["catalog"] or catalog != seed_catalog() else None,
        "text": "\n".join(log),
        "rolls": rolls,
        "attacks": outcomes,
    }
