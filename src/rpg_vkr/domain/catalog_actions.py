"""Small explicit homebrew resolver for newly registered actors; no moral gate."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.catalog import Catalog, Entity, effective_properties, json_data
from rpg_vkr.domain.character import AbilityCheck, resolve_ability_check
from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.dice import D20Roll
from rpg_vkr.domain.interactions import InteractiveWorld, identifier, label
from rpg_vkr.domain.world import WorldState

OPERATIONS = {"attack", "heal", "help", "hinder", "insult"}


def bind_attempt(text, operation, lethal, *, confirmed=False):
    import re

    from rpg_vkr.narrative.speech import unquoted

    value = unquoted(text).casefold()
    roots = {
        "attack": r"атак\w*|удар\w*|бью|бить|уби\w*|убь\w*|доб\w*|вонз\w*|реж\w*",
        "heal": r"леч\w*|перевяз\w*|бинт\w*",
        "help": r"помо\w*|подсоб\w*|поддерж\w*",
        "hinder": r"меш\w*|помех\w*|сорв\w*",
        "insult": r"оскор\w*|обид\w*|груб\w*",
    }
    if operation not in roots:
        raise ValueError("Неизвестный вид намерения.")
    if re.search(r"\b(?:если|можно ли|могу ли|цитирую|спрашиваю)\b", value):
        raise ValueError("Вопрос или условие не выполняют попытку.")
    negative = (
        r"\bне\s+(?:(?:хочу|буду|собираюсь|стану)\s+)?"
        r"(?:(?:его|её|ее|их|тебя|вас|никого)\s+)?(?:" + roots[operation] + r")"
    )
    if re.search(negative, value):
        raise ValueError("Отрицание намерения не выполняет попытку.")
    if operation != "insult" and re.match(r"(?:я\s+)?(?:говорю|обещаю|угрожаю|пишу)\b", value):
        raise ValueError("Слова о действии не являются физической попыткой.")
    if not confirmed and not re.search(r"\b(?:" + roots[operation] + r")", value):
        raise ValueError("Нужно подтвердить, как понято намерение.")
    if lethal and not re.search(r"уби|убь|доб|смерт|горл|сердц", value):
        raise ValueError("Смертельное намерение не указано игроком.")


def attempt_parameters(catalog, target_id, operation, character, legacy_entity=None):
    if operation not in OPERATIONS:
        raise ValueError("Неизвестный вид попытки.")
    target = next((e for e in catalog.entities if e.id == target_id), None)
    if target is None and target_id in ACTORS and legacy_entity is not None:
        from rpg_vkr.domain.catalog import Definition

        spec = ACTORS[target_id]
        target = legacy_entity
        definition = Definition(
            "type_actor_" + target_id,
            spec[0],
            "actor",
            ("npcs",),
            {"hp_max": spec[2], "defence": spec[3]},
            origin="legacy-adapter",
        )
    elif target is None:
        raise ValueError("Такое существо не зарегистрировано.")
    else:
        definition = next(d for d in catalog.definitions if d.id == target.definition_id)
    if definition.kind != "actor":
        raise ValueError("Эта попытка направлена на существо.")
    if operation == "attack":
        ability = "dexterity" if character.dexterity > character.strength else "strength"
        properties, _ = effective_properties(catalog, definition)
        difficulty = max(5, min(25, properties.get("defence", 10)))
    elif operation == "heal":
        ability, difficulty = "wisdom", 10
    elif operation == "help":
        ability, difficulty = "wisdom", 10
    else:
        ability, difficulty = "charisma", 10
    return target, definition, ability, difficulty


@dataclass(frozen=True)
class CounterAttack:
    roll: D20Roll
    total: int
    defence: int
    damage: int


@dataclass(frozen=True)
class ActorAttempt:
    operation: str
    target_id: str
    lethal: bool
    reason: str
    model: str
    base_turn: int
    before: InteractiveWorld
    world_before: WorldState
    world_after: WorldState
    entity_before: Entity
    entity_after: Entity
    roll: D20Roll
    check: AbilityCheck
    summary: str
    rules_version: str = "catalog-actor-homebrew-1"
    counter: CounterAttack | None = None

    def to_dict(self):
        result = asdict(self) | {
            "before": self.before.to_dict(),
            "entity_before": self.entity_before.to_dict(),
            "entity_after": self.entity_after.to_dict(),
        }
        if self.rules_version == "catalog-actor-homebrew-1":
            result.pop("counter")
        return result


def resolve_attempt(
    catalog,
    scene,
    world,
    character,
    target_id,
    operation,
    lethal,
    roll,
    reason,
    model,
    base_turn,
    legacy_entity=None,
    counter_roll=None,
    preview=False,
):
    identifier(target_id)
    label(reason, 400)
    label(model, 128)
    if type(lethal) is not bool or (lethal and operation != "attack"):
        raise ValueError("Неверное указание смертельного намерения.")
    target, definition, ability, difficulty = attempt_parameters(
        catalog, target_id, operation, character, legacy_entity
    )
    if not any(a.id == target_id and a.place == scene.current for a in scene.actor_refs):
        raise ValueError("Цели нет рядом; действие до неё не достигает.")
    state = dict(target.state or {})
    if state.get("life") == "dead":
        raise ValueError("Цель мертва; обычная атака или лечение не меняют это состояние.")
    hp = state.get("hp", definition.properties["hp_max"])
    if operation == "attack" and hp == 0 and not lethal:
        raise ValueError("Цель уже повержена; уточните, чего хотите добиться.")
    if operation == "heal" and (world.bandages < 1 or hp >= definition.properties["hp_max"]):
        raise ValueError("Для лечения нужен бинт и раненая живая цель.")
    check = resolve_ability_check(ability, character.score(ability), roll.value, difficulty)
    after_world = world
    name = definition.name
    if operation == "attack":
        # Authored base, not SRD damage: the die resolves hit and never supplies pure damage.
        damage = max(1, 2 + check.modifier) if check.succeeded else 0
        state["hp"] = max(0, hp - damage)
        state["disposition"] = "hostile"
        if state["hp"] == 0:
            state["life"] = "dead" if lethal and check.succeeded else "defeated"
        summary = (
            f"Атака достигла цели: {name}. Урон: {damage}."
            if damage
            else f"Атака не достигла цели: {name}. Промах."
        )
        if state.get("life") == "dead":
            summary += " Цель погибла. Добыча не выдавалась."
        elif state.get("life") == "defeated":
            summary += " Цель повержена."
    elif operation == "heal":
        after_world = replace(world, bandages=world.bandages - 1)
        healing = min(4, definition.properties["hp_max"] - hp) if check.succeeded else 0
        state["hp"] = hp + healing
        if healing:
            state.pop("life", None)
        summary = (
            f"Перевязка помогла: {name}. Восстановлено {healing} ОЗ."
            if healing
            else f"Перевязка пока не помогла: {name}."
        )
        summary += " Использован один ваш бинт."
    else:
        relations = json_data(state.get("relations", {}))
        hero = dict(relations.get("hero", {}))
        field = "trust" if operation == "help" else "grievance"
        if check.succeeded:
            hero[field] = max(-10, min(10, hero.get(field, 0) + 1))
        relations["hero"] = hero
        state["relations"] = relations
        description = {
            "help": "попытка помощи",
            "hinder": "попытка помешать",
            "insult": "обидная реплика",
        }[operation]
        summary = f"{name}: {description} " + (
            "повлияла на отношение." if check.succeeded else "не дала ожидаемого влияния."
        )
    counter = None
    rules_version = (
        "catalog-actor-homebrew-2"
        if scene.version == "interactive-world-4"
        else "catalog-actor-homebrew-1"
    )
    if operation == "attack" and rules_version.endswith("-2") and state["hp"] > 0:
        if counter_roll is None and not preview:
            raise ValueError("Не хватает ответного броска противника.")
        if counter_roll:
            from rpg_vkr.domain.character import ability_modifier

            bonus = definition.properties.get("attack_bonus", 1)
            base_damage = definition.properties.get("attack_damage", 2)
            if (
                type(bonus) is not int
                or not -5 <= bonus <= 20
                or type(base_damage) is not int
                or not 1 <= base_damage <= 100
            ):
                raise ValueError("Некорректные боевые параметры существа.")
            defence = 10 + max(0, ability_modifier(character.dexterity))
            total = counter_roll.value + bonus
            damage = min(world.hp, base_damage) if total >= defence else 0
            counter = CounterAttack(counter_roll, total, defence, damage)
            after_world = replace(after_world, hp=after_world.hp - damage)
            summary += (
                f" Ответный удар: потеряно {damage} ОЗ."
                if damage
                else " Ответный удар прошёл мимо."
            )
            if after_world.hp == 0:
                summary += " Герой выбыл."
    elif counter_roll is not None:
        raise ValueError("У этого действия нет ответного удара.")
    after = replace(target, state=state)
    record = ActorAttempt(
        operation,
        target_id,
        lethal,
        reason,
        model,
        base_turn,
        scene,
        world,
        after_world,
        target,
        after,
        roll,
        check,
        summary,
        rules_version,
        counter,
    )
    updated = Catalog(
        catalog.definitions, tuple(after if e.id == target_id else e for e in catalog.entities)
    )
    return updated, after_world, record


def restore_attempt(data, catalog, dice, character):
    fields = set(ActorAttempt.__dataclass_fields__)
    if isinstance(data, dict) and data.get("rules_version") == "catalog-actor-homebrew-1":
        fields.remove("counter")
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Неверная запись попытки с существом.")
    roll = dice.roll_d20()
    if asdict(roll) != data["roll"]:
        raise ValueError("Изменён бросок попытки.")
    values = dict(data)
    if data.get("counter") is not None:
        raw_counter = data["counter"]
        counter_roll = dice.roll_d20()
        if asdict(counter_roll) != raw_counter["roll"]:
            raise ValueError("Изменён ответный бросок.")
        values["counter"] = CounterAttack(**(raw_counter | {"roll": counter_roll}))
    values.update(
        before=InteractiveWorld.from_dict(data["before"]),
        world_before=WorldState.from_dict(data["world_before"]),
        world_after=WorldState.from_dict(data["world_after"]),
        entity_before=Entity.from_dict(data["entity_before"]),
        entity_after=Entity.from_dict(data["entity_after"]),
        roll=roll,
        check=AbilityCheck(**data["check"]),
    )
    record = ActorAttempt(**values)
    result = Catalog(
        catalog.definitions,
        tuple(record.entity_after if e.id == record.target_id else e for e in catalog.entities),
    )
    after_world = record.world_after
    if json_data(record.to_dict(), limit=500000) != json_data(data, limit=500000):
        raise ValueError("Последствия попытки не совпадают с расчётом.")
    return result, after_world, record
