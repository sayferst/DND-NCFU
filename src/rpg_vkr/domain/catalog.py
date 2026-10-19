"""Typed catalog definitions and persistent instances; model text never executes code."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rpg_vkr.domain.interactions import ActorRef, InteractiveWorld, Thing, identifier, label

CATEGORIES = {
    "quest": "1. Квестовые предметы",
    "materials": "2. Материалы",
    "weapons": "3. Оружие и боеприпасы",
    "plants": "4. Растения",
    "medicine": "5. Медицина и зелья",
    "npcs": "6. Встреченные NPC",
    "creatures": "7. Животные и мобы",
    "bosses": "8. Боссы",
    "armour": "9. Броня и сбруя",
    "miscellaneous": "10. Прочие предметы",
}
RARITIES = {"common", "uncommon", "rare", "very_rare", "legendary", "unique"}


def json_data(value, *, limit=12000):
    """Bounded JSON data, not Python/SQL, including extensible descriptive properties."""

    def visit(item, depth=0):
        if depth > 8:
            raise ValueError("Слишком глубокие свойства каталога.")
        if item is None or type(item) is bool:
            return
        if type(item) in (int, float):
            if not -1_000_000_000 <= item <= 1_000_000_000:
                raise ValueError("Некорректное числовое свойство.")
        elif isinstance(item, str):
            if len(item) > 4000 or any(ord(c) < 32 and c not in "\n\t" for c in item):
                raise ValueError("Некорректный текст свойства.")
        elif isinstance(item, (list, tuple)):
            if len(item) > 100:
                raise ValueError("Слишком длинный список свойств.")
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, dict):
            if len(item) > 50 or any(not isinstance(k, str) or len(k) > 80 for k in item):
                raise ValueError("Некорректные ключи свойства.")
            for child in item.values():
                visit(child, depth + 1)
        else:
            raise ValueError("Свойства должны быть JSON-данными.")

    visit(value)
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(result) > limit:
        raise ValueError("Запись каталога слишком велика.")
    return json.loads(result)


@dataclass(frozen=True)
class Definition:
    id: str
    name: str
    kind: str
    categories: tuple[str, ...]
    properties: dict
    rarity: str = "common"
    price_cp: int | None = None
    materials: tuple[dict, ...] = ()
    effects: tuple[dict, ...] = ()
    loot: tuple[dict, ...] = ()
    origin: str = "generated"

    def __post_init__(self):
        identifier(self.id)
        label(self.name, 100)
        if self.kind not in {"item", "material", "actor"}:
            raise ValueError("Неизвестный вид сущности каталога.")
        if not self.categories or not set(self.categories) <= CATEGORIES.keys():
            raise ValueError("Неизвестный раздел каталога.")
        if len(set(self.categories)) != len(self.categories) or self.rarity not in RARITIES:
            raise ValueError("Повторный раздел или неверная редкость.")
        if self.price_cp is not None and (
            type(self.price_cp) is not int or not 0 <= self.price_cp <= 1_000_000_000
        ):
            raise ValueError("Неверная цена в медных единицах.")
        if self.origin not in {"project-homebrew", "generated", "legacy-adapter"}:
            raise ValueError("Неизвестное происхождение записи.")
        if not isinstance(self.properties, dict):
            raise ValueError("Свойства должны быть объектом.")
        json_data(self.to_dict())
        for key in (
            "mass_g",
            "volume_ml",
            "capacity_ml",
            "max_load_g",
            "durability",
            "defence",
            "penetration",
            "processing_difficulty",
            "hp_max",
        ):
            if key in self.properties and (
                type(self.properties[key]) is not int or self.properties[key] < 0
            ):
                raise ValueError("Неверное свойство: " + key)
        for key in ("container", "portable", "open", "locked", "leakproof"):
            if key in self.properties and type(self.properties[key]) is not bool:
                raise ValueError("Неверное логическое свойство: " + key)
        if self.kind == "actor" and not 1 <= self.properties.get("hp_max", 0) <= 100000:
            raise ValueError("Существу требуется положительный максимум здоровья.")
        modifiers = self.properties.get("equipment_modifiers", {})
        if not isinstance(modifiers, dict) or not set(modifiers) <= {
            "defence",
            "penetration",
            "durability",
        }:
            raise ValueError("Неверные модификаторы материала.")
        if any(type(v) is not int or not -1000 <= v <= 1000 for v in modifiers.values()):
            raise ValueError("Неверная величина модификатора материала.")
        for row in self.materials:
            if set(row) != {"definition_id", "parts"} or type(row["parts"]) is not int:
                raise ValueError("Неверный состав предмета.")
            identifier(row["definition_id"])
            if not 1 <= row["parts"] <= 10000:
                raise ValueError("Неверная доля материала.")
        for row in self.effects:
            if set(row) != {"kind", "magnitude", "duration_turns", "description"}:
                raise ValueError("Неверный эффект предмета.")
            identifier(row["kind"])
            label(row["description"], 400)
            if type(row["magnitude"]) is not int or not -10000 <= row["magnitude"] <= 10000:
                raise ValueError("Неверная величина эффекта.")
            if type(row["duration_turns"]) is not int or not 0 <= row["duration_turns"] <= 100000:
                raise ValueError("Неверная длительность эффекта.")
        for row in self.loot:
            if set(row) != {"definition_id", "min_qty", "max_qty", "chance_percent"}:
                raise ValueError("Неверная таблица возможной добычи.")
            identifier(row["definition_id"])
            if any(type(row[k]) is not int for k in ("min_qty", "max_qty", "chance_percent")):
                raise ValueError("Неверные числа добычи.")
            if (
                not 0 <= row["min_qty"] <= row["max_qty"] <= 10000
                or not 0 <= row["chance_percent"] <= 100
            ):
                raise ValueError("Неверные пределы добычи.")

    def to_dict(self):
        return json_data(
            {
                "id": self.id,
                "name": self.name,
                "kind": self.kind,
                "categories": list(self.categories),
                "properties": self.properties,
                "rarity": self.rarity,
                "price_cp": self.price_cp,
                "materials": list(self.materials),
                "effects": list(self.effects),
                "loot": list(self.loot),
                "origin": self.origin,
            }
        )

    @classmethod
    def from_dict(cls, data):
        data = json_data(data)
        if (
            not isinstance(data, dict)
            or not {"id", "name", "kind", "categories", "properties"} <= data.keys()
        ):
            raise ValueError("Не хватает полей типа каталога.")
        for key in ("categories", "materials", "effects", "loot"):
            if key in data:
                if not isinstance(data[key], list):
                    raise ValueError("Неверный список типа каталога.")
                data[key] = tuple(data[key])
        return cls(**data)


@dataclass(frozen=True)
class Entity:
    id: str
    definition_id: str
    parent_id: str
    owner_id: str = ""
    quantity: int = 1
    state: dict | None = None

    def __post_init__(self):
        for value in (self.id, self.definition_id, self.parent_id):
            identifier(value)
        if not isinstance(self.owner_id, str):
            raise ValueError("Неверный ID владельца.")
        if self.owner_id:
            identifier(self.owner_id)
        if type(self.quantity) is not int or not 1 <= self.quantity <= 1000000:
            raise ValueError("Неверное количество экземпляров.")
        if self.state is not None and not isinstance(self.state, dict):
            raise ValueError("Неверное состояние экземпляра.")
        for key in ("locked", "open"):
            if key in (self.state or {}) and type(self.state[key]) is not bool:
                raise ValueError("Неверное состояние доступа к контейнеру.")
        json_data(self.to_dict())

    def to_dict(self):
        return json_data(
            {
                "id": self.id,
                "definition_id": self.definition_id,
                "parent_id": self.parent_id,
                "owner_id": self.owner_id,
                "quantity": self.quantity,
                "state": self.state or {},
            }
        )

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Неверный экземпляр каталога.")
        return cls(**json_data(data))


@dataclass(frozen=True)
class Catalog:
    definitions: tuple[Definition, ...] = ()
    entities: tuple[Entity, ...] = ()
    version: str = "catalog-1"

    def __post_init__(self):
        if self.version != "catalog-1" or len(self.definitions) > 2000 or len(self.entities) > 2000:
            raise ValueError("Превышен предел каталога пилота.")
        definitions = {d.id: d for d in self.definitions}
        if len(definitions) != len(self.definitions) or len({e.id for e in self.entities}) != len(
            self.entities
        ):
            raise ValueError("Повторный ID в каталоге.")
        if set(definitions) & {e.id for e in self.entities}:
            raise ValueError("ID типа и экземпляра должны различаться.")
        for d in self.definitions:
            for row in (*d.materials, *d.loot):
                target = definitions.get(row["definition_id"])
                if not target or target.kind == "actor":
                    raise ValueError("Состав или добыча ссылаются на неизвестный тип.")

        complete = set()

        def visit(current, seen):
            if current.id in seen or len(seen) > 64:
                raise ValueError("Циклический или слишком глубокий состав предмета.")
            if current.id in complete:
                return
            for row in current.materials:
                visit(definitions[row["definition_id"]], seen | {current.id})
            complete.add(current.id)

        for d in self.definitions:
            visit(d, set())
        for e in self.entities:
            if e.definition_id not in definitions:
                raise ValueError("Экземпляр ссылается на неизвестный тип.")
            d = definitions[e.definition_id]
            state = e.state or {}
            if d.kind == "actor":
                if e.quantity != 1:
                    raise ValueError("У каждого существа должен быть собственный ID.")
                hp = state.get("hp", d.properties["hp_max"])
                if type(hp) is not int or not 0 <= hp <= d.properties["hp_max"]:
                    raise ValueError("Неверное здоровье существа.")
            for key in ("gold_cp", "condition", "charges"):
                if key in state and (type(state[key]) is not int or state[key] < 0):
                    raise ValueError("Неверное динамическое состояние.")
            relations = state.get("relations", {})
            if not isinstance(relations, dict) or any(
                not isinstance(v, dict) for v in relations.values()
            ):
                raise ValueError("Неверная структура отношений.")
            for relation in relations.values():
                for key in ("trust", "fear", "respect", "grievance"):
                    if key in relation and (
                        type(relation[key]) is not int or not -10 <= relation[key] <= 10
                    ):
                        raise ValueError("Неверный показатель отношений.")

    def to_dict(self):
        return {
            "version": self.version,
            "definitions": [d.to_dict() for d in self.definitions],
            "entities": [e.to_dict() for e in self.entities],
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {"version", "definitions", "entities"}:
            raise ValueError("Неверная структура каталога.")
        return cls(
            tuple(Definition.from_dict(d) for d in data["definitions"]),
            tuple(Entity.from_dict(e) for e in data["entities"]),
            data["version"],
        )


@lru_cache(maxsize=1)
def seed_payload():
    path = Path(__file__).resolve().parents[3] / "data/catalog/seed-v1.json"
    return json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False)


def seed_catalog():
    return Catalog.from_dict(json.loads(seed_payload()))


def effective_properties(catalog, definition):
    """Authored weighted material modifiers, shared by any generated equipment/body."""
    definitions = {
        d.id: d for d in (catalog.definitions if isinstance(catalog, Catalog) else catalog)
    }
    values = dict(definition.properties)
    trace = {}
    materials = [(definitions[r["definition_id"]], r["parts"]) for r in definition.materials]
    weight = sum(parts for _, parts in materials)
    if weight:
        for stat in ("defence", "penetration", "durability"):
            bonus = (
                sum(
                    d.properties.get("equipment_modifiers", {}).get(stat, 0) * parts
                    for d, parts in materials
                )
                // weight
            )
            if stat in values or bonus:
                base = values.get(
                    stat, 10 if definition.kind == "actor" and stat == "defence" else 0
                )
                values[stat] = max(0, base + bonus)
                trace[stat] = {"base": base, "material_bonus": bonus, "total": values[stat]}
    return values, trace


@dataclass(frozen=True)
class Registration:
    definitions: tuple[Definition, ...]
    entities: tuple[Entity, ...]
    reason: str
    model: str
    base_turn: int
    before: InteractiveWorld

    def __post_init__(self):
        label(self.reason, 400)
        label(self.model, 128)
        if type(self.base_turn) is not int or not 0 <= self.base_turn <= 2000:
            raise ValueError("Неверный ход создания сущности.")
        if not 0 < len(self.definitions) + len(self.entities) <= 12:
            raise ValueError("За ход можно зарегистрировать до 12 записей.")

    def to_dict(self):
        return {
            "definitions": [d.to_dict() for d in self.definitions],
            "entities": [e.to_dict() for e in self.entities],
            "reason": self.reason,
            "model": self.model,
            "base_turn": self.base_turn,
            "before": self.before.to_dict(),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Неверное событие регистрации.")
        return cls(
            tuple(Definition.from_dict(d) for d in data["definitions"]),
            tuple(Entity.from_dict(e) for e in data["entities"]),
            data["reason"],
            data["model"],
            data["base_turn"],
            InteractiveWorld.from_dict(data["before"]),
        )


def register(catalog, world, record):
    """Create canon only in the present scene. A definition alone is not an owned item."""
    from dataclasses import replace

    if record.before != world:
        raise ValueError("Сцена регистрации устарела.")
    existing_defs = {d.id for d in catalog.definitions}
    existing_entities = (
        {e.id for e in catalog.entities}
        | {t.id for t in world.things}
        | {a.id for a in world.actor_refs}
        | {p.id for p in world.places}
        | {"hero"}
    )
    if any(d.id in existing_defs for d in record.definitions):
        raise ValueError("Установленный тип нельзя незаметно перезаписать.")
    if any(e.id in existing_entities for e in record.entities):
        raise ValueError("Установленную сущность нельзя незаметно заменить.")
    if any(
        r.id.startswith(("legacy_", "resource_", "trade_", "type_actor_", "imported_type_"))
        or r.id == "type_currency"
        for r in (*record.definitions, *record.entities)
    ):
        raise ValueError("Этот диапазон ID зарезервирован адаптером старых данных.")
    if any(d.origin != "generated" for d in record.definitions):
        raise ValueError("Модель может создавать только записи с происхождением generated.")
    result = Catalog(catalog.definitions + record.definitions, catalog.entities + record.entities)
    types = {d.id: d for d in result.definitions}
    actors = list(world.actor_refs)
    things = list(world.things)
    for e in record.entities:
        if types[e.definition_id].kind == "actor":
            if e.parent_id != world.current or e.owner_id:
                raise ValueError("Новое существо появляется в текущей сцене без владельца.")
            actors.append(ActorRef(e.id, types[e.definition_id].name, e.parent_id))
    actor_ids = {a.id for a in actors}
    for e in record.entities:
        d = types[e.definition_id]
        if d.kind == "actor":
            continue
        if e.parent_id == "hero":
            raise ValueError("Создание не выдаёт новую вещь герою без действия получения.")
        new_container_ids = {
            item.id
            for item in record.entities
            if types[item.definition_id].properties.get("container", False)
        }
        if e.parent_id not in {world.current, *actor_ids, *new_container_ids}:
            raise ValueError("Новая вещь должна появиться в доступной сцене.")
        if e.parent_id in actor_ids and not any(
            a.id == e.parent_id and a.place == world.current for a in actors
        ):
            raise ValueError("Нельзя изменять имущество удалённого персонажа.")
        if e.owner_id and e.owner_id not in actor_ids | {"hero"}:
            raise ValueError("Неизвестный собственник новой вещи.")
        things.append(
            Thing(
                e.id,
                d.name,
                e.parent_id,
                e.owner_id,
                e.quantity,
                d.properties.get("container", False),
                {"type_bandage": "bandages"}.get(d.id, "")
                if world.version in {"interactive-world-3", "interactive-world-4"}
                else "",
            )
        )
    expanded = replace(
        world,
        things=tuple(things),
        actors=tuple(actors),
        version=world.version
        if world.version in {"interactive-world-3", "interactive-world-4"}
        else "interactive-world-2",
    )
    return result, expanded


def validate_plan_properties(catalog, world, plan, *, turn_index, aliases=None):
    """Apply represented physical properties to any registered type, irrespective of its name."""
    from rpg_vkr.domain.interactions import WorldPlan, apply_plan

    definitions = {d.id: d for d in catalog.definitions}
    entities = {e.id: e for e in catalog.entities}
    defaults = {"apples": "type_apple", "produce_basket": "type_basket"}
    aliases = dict(aliases or {})
    aliases.update({f"split_{turn_index}_{j}": step.target for j, step in enumerate(plan.steps)})

    def properties(id):
        seen = set()
        while id in aliases and id not in seen:
            seen.add(id)
            id = aliases[id]
        thing = next((t for t in world.things if t.id == id), None)
        if thing and thing.resource:
            from rpg_vkr.domain.resources import properties as resource_properties

            return resource_properties(world, id, catalog)
        e = entities.get(id)
        type_id = e.definition_id if e else defaults.get(id)
        if type_id not in definitions:
            return {}
        values = dict(definitions[type_id].properties)
        if e:
            values.update({k: v for k, v in (e.state or {}).items() if k in {"open", "locked"}})
        return values

    for i, step in enumerate(plan.steps):
        prefix = plan.steps[:i]
        visited = {s.target for s in prefix if s.op == "move"}
        places = tuple(p for p in plan.places if p.id in visited)
        current, _, _, _ = apply_plan(world, WorldPlan(prefix, places), turn_index=turn_index)
        things = {t.id: t for t in current.things}
        if step.op in {"take", "put", "drop", "give", "look"} and step.target in things:
            cursor = things[step.target]
            if step.op == "take" and properties(cursor.id).get("portable") is False:
                raise ValueError("Предмет закреплён или непереносим; простого взятия недостаточно.")
            while cursor.holder in things:
                cursor = things[cursor.holder]
                if properties(cursor.id).get("locked"):
                    raise ValueError("Контейнер заперт; сначала нужен допустимый способ доступа.")
            if step.op == "look" and properties(step.target).get("locked"):
                raise ValueError("Контейнер заперт; содержимое отсюда не видно.")
        if step.op != "put":
            continue
        target_props = properties(step.destination)
        if target_props.get("locked"):
            raise ValueError("Нельзя положить вещь в запертый контейнер.")
        prefix = plan.steps[: i + 1]
        visited = {s.target for s in prefix if s.op == "move"}
        after, _, _, _ = apply_plan(
            world,
            WorldPlan(prefix, tuple(p for p in plan.places if p.id in visited)),
            turn_index=turn_index,
        )
        for field, maximum in (("volume_ml", "capacity_ml"), ("mass_g", "max_load_g")):
            if maximum not in target_props:
                continue
            total = 0
            for thing in after.things:
                cursor, nested = thing, False
                while cursor.holder in {t.id for t in after.things}:
                    if cursor.holder == step.destination:
                        nested = True
                        break
                    cursor = next(t for t in after.things if t.id == cursor.holder)
                if thing.holder != step.destination and not (field == "mass_g" and nested):
                    continue
                value = properties(thing.id).get(field)
                if value is None:
                    raise ValueError("Не задан " + field + "; вместимость нельзя подтвердить.")
                total += value * thing.quantity
            if total > target_props[maximum]:
                raise ValueError("Вместимость или допустимая масса контейнера превышена.")
