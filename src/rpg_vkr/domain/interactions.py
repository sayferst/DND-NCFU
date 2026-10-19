"""Generic possessions, containers and adjacent places, changed by checked transactions."""

import json
import re
from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.character import AbilityCheck, resolve_ability_check
from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.dice import D20Roll
from rpg_vkr.domain.world import LOCATIONS


class PlanConfirmationRequired(ValueError):
    """Unfamiliar wording can be confirmed instead of requiring a fixed command."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value):
        raise ValueError("Неверный идентификатор объекта мира.")


def label(value, limit=240):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
        or re.search(r"[<>]|https?://", value)
    ):
        raise ValueError("Неверное описание объекта мира.")


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    parent: str
    anchor: str
    description: str = ""

    def __post_init__(self):
        identifier(self.id)
        label(self.name, 80)
        if self.anchor not in LOCATIONS or (self.parent and self.parent == self.id):
            raise ValueError("Неверная связь мест.")
        if self.parent:
            identifier(self.parent)
        if self.description:
            label(self.description, 400)


@dataclass(frozen=True)
class Thing:
    id: str
    name: str
    holder: str
    owner: str
    quantity: int
    container: bool = False
    resource: str = ""

    def __post_init__(self):
        for value in (self.id, self.holder):
            identifier(value)
        if self.owner:
            identifier(self.owner)
        label(self.name, 80)
        if type(self.quantity) is not int or not 1 <= self.quantity <= 1000000:
            raise ValueError("Неверное количество предметов.")
        if type(self.container) is not bool or (self.container and self.quantity != 1):
            raise ValueError("Неверный контейнер.")
        if self.resource not in {"", "gold", "bandages"} or self.resource and self.container:
            raise ValueError("Неверный ресурс предмета.")


@dataclass(frozen=True)
class ActorRef:
    id: str
    name: str
    place: str

    def __post_init__(self):
        identifier(self.id)
        identifier(self.place)
        label(self.name, 100)


@dataclass(frozen=True)
class InteractiveWorld:
    current: str
    places: tuple[Place, ...]
    things: tuple[Thing, ...]
    version: str = "interactive-world-1"
    actors: tuple[ActorRef, ...] = ()

    @property
    def actor_refs(self):
        return (
            self.actors
            if self.version in {"interactive-world-2", "interactive-world-3"}
            else tuple(ActorRef(key, spec[0], spec[1]) for key, spec in ACTORS.items())
        )

    def __post_init__(self):
        if (
            self.version
            not in {"interactive-world-1", "interactive-world-2", "interactive-world-3"}
            or not 3 <= len(self.places) <= 40
            or len(self.things) > (80 if self.version == "interactive-world-1" else 2000)
        ):
            raise ValueError("Мир превышает поддерживаемые пределы.")
        places = {p.id: p for p in self.places}
        things = {t.id: t for t in self.things}
        actors = {a.id: a for a in self.actor_refs}
        if len(actors) != len(self.actor_refs) or any(
            a.place not in places for a in actors.values()
        ):
            raise ValueError("Неверное размещение существ.")
        if len(places) != len(self.places) or len(things) != len(self.things):
            raise ValueError("Повторный идентификатор объекта.")
        if set(places) & (set(things) | set(actors) | {"hero"}) or set(things) & (
            set(actors) | {"hero"}
        ):
            raise ValueError("Пересечение идентификаторов мира.")
        if self.current not in places or not set(LOCATIONS) <= set(places):
            raise ValueError("Неизвестное текущее место.")
        for p in self.places:
            seen, cursor = set(), p
            while cursor.parent:
                if cursor.id in seen or cursor.parent not in places:
                    raise ValueError("Цикл или отсутствующее место.")
                seen.add(cursor.id)
                cursor = places[cursor.parent]
        for thing in self.things:
            if thing.resource and self.version != "interactive-world-3":
                raise ValueError("Физические ресурсы требуют новую версию мира.")
            if self.version == "interactive-world-1" and thing.quantity > 100:
                raise ValueError("Количество превышает предел старой версии мира.")
            cursor, seen = thing, set()
            while cursor.holder in things:
                if cursor.id in seen or not things[cursor.holder].container:
                    raise ValueError("Цикл или неверный контейнер.")
                seen.add(cursor.id)
                cursor = things[cursor.holder]
            if cursor.holder not in {*places, *actors, "hero"} or thing.owner not in {
                *actors,
                "hero",
                *(set() if self.version == "interactive-world-1" else {""}),
            }:
                raise ValueError("Неизвестный держатель или собственник.")

    @classmethod
    def initial(cls, location):
        return cls(
            location,
            (
                Place("gate", LOCATIONS["gate"], "", "gate"),
                Place("road", LOCATIONS["road"], "gate", "road"),
                Place("market", LOCATIONS["market"], "gate", "market"),
            ),
            (
                Thing("produce_basket", "Плетёная корзина", "villager", "villager", 1, True),
                Thing("apples", "Яблоки", "produce_basket", "villager", 12),
            ),
        )

    def place(self, id=None):
        return next(p for p in self.places if p.id == (id or self.current))

    def root_holder(self, thing):
        things = {t.id: t for t in self.things}
        while thing.holder in things:
            thing = things[thing.holder]
        return thing.holder

    def here(self, thing):
        holder = self.root_holder(thing)
        return (
            holder == "hero"
            or holder == self.current
            or any(a.id == holder and a.place == self.current for a in self.actor_refs)
        )

    def carried(self):
        return tuple(t for t in self.things if self.root_holder(t) == "hero")

    def inventory(self):
        items = self.carried()
        return "; ".join(f"{t.name} ×{t.quantity}" for t in items) or "нет дополнительных предметов"

    def context(self):
        return {
            "current": self.current,
            "place": asdict(self.place()),
            "places": [asdict(p) for p in self.places],
            "objects": [self.thing_dict(t) | {"available_here": self.here(t)} for t in self.things],
            "actors_here": [a.id for a in self.actor_refs if a.place == self.current],
        }

    def to_dict(self):
        value = asdict(self)
        value["things"] = [self.thing_dict(t) for t in self.things]
        if self.version == "interactive-world-1":
            value.pop("actors")
        return value

    def thing_dict(self, thing):
        value = asdict(thing)
        if self.version != "interactive-world-3":
            value.pop("resource")
        return value

    @classmethod
    def from_dict(cls, data):
        fields = set(cls.__dataclass_fields__)
        if isinstance(data, dict) and data.get("version") == "interactive-world-1":
            fields.discard("actors")
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("Неверное состояние предметов мира.")
        return cls(
            data["current"],
            tuple(Place(**p) for p in data["places"]),
            tuple(Thing(**t) for t in data["things"]),
            data["version"],
            tuple(ActorRef(**a) for a in data.get("actors", ())),
        )


@dataclass(frozen=True)
class Step:
    op: str
    target: str
    quantity: int = 1
    destination: str = ""

    def __post_init__(self):
        if self.op not in {"take", "drop", "put", "give", "move", "look", "inventory"}:
            raise ValueError("Эта операция мира пока не поддержана.")
        if self.target:
            identifier(self.target)
        if self.destination:
            identifier(self.destination)
        if type(self.quantity) is not int or not 0 <= self.quantity <= 1000000:
            raise ValueError("Неверное количество в действии.")


@dataclass(frozen=True)
class WorldPlan:
    steps: tuple[Step, ...]
    places: tuple[Place, ...] = ()

    def __post_init__(self):
        if len(self.steps) > 6 or len(self.places) > 2:
            raise ValueError("Разделите длинную цепочку действий на несколько сообщений.")
        if self.places and not self.steps:
            raise ValueError("Новое место требует подтверждённого перехода.")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {"steps", "places"}:
            raise ValueError("Неверный план действий мира.")
        if not isinstance(data["steps"], (tuple, list)) or not isinstance(
            data["places"], (tuple, list)
        ):
            raise ValueError("Неверный список действий.")
        return cls(
            tuple(Step(**s) for s in data["steps"]), tuple(Place(**p) for p in data["places"])
        )


def bind_plan(text, plan, *, confirmed=False):
    from rpg_vkr.narrative.speech import unquoted

    value = re.sub(r"\b(?:ничего не говоря|не говоря ни слова)\b", "молча", unquoted(text))
    changes_world = any(s.op not in {"look", "inventory"} for s in plan.steps)
    if changes_world and (
        "?" in text
        or re.search(r"\b(?:если|не|цитирую|говорю|спрашиваю|могу ли|можно ли)\b", value)
    ):
        raise ValueError("Вопрос, отрицание или речь не подтверждают изменение мира.")
    cues = {
        "take": r"бер|взя|взять|возьм|забир|забер|прихват|утащ|хват|крад|укра|содержим",
        "drop": r"брос|выбрас|выкин|выкид|остав|выки[нд]",
        "put": r"клад|кладу|лож|переклад|убира|помещ",
        "give": r"даю|отда|возвращ|верн|переда|вруча|дарю",
        "move": r"ид[ту]|пой[дт]|бег|убеж|ухож|уй[дт]|направ|дви[гж]|отправ|глуб|прочь|верн",
    }
    for step in plan.steps:
        if step.op in cues and not re.search(cues[step.op], value) and not confirmed:
            raise PlanConfirmationRequired("Подтвердите, как мастер понял вашу формулировку.")


def requests_physical_change(text):
    """A guard against narrating a clear transfer/travel request without an executed plan."""
    from rpg_vkr.narrative.speech import unquoted

    value = re.sub(
        r"\b(?:ничего не говоря|не говоря ни слова)\b", "молча", unquoted(text).casefold()
    )
    if "?" in text or re.search(r"\b(?:если|не|говорю|спрашиваю|можно ли|могу ли)\b", value):
        return False
    return bool(
        re.search(
            r"\b(?:беру|взять|возьму|забира\w*|заберу|прихва\w*|утащ\w*|краду|украду|"
            r"выбрас\w*|выкид\w*|выкин\w*|выбро\w*|переклад\w*|переда\w*|отда\w*|"
            r"возвращаю\w*|убег\w*|убеж\w*|ухожу|уйду|пойду|иду|отправл\w*)\b",
            value,
        )
    )


def apply_plan(before, plan, *, check_succeeded=True, turn_index=1):
    """Pure, all-or-nothing validation. No object creation, money or free teleportation."""
    places = list(before.places)
    for new in plan.places:
        if any(p.id == new.id for p in places) or new.parent not in {p.id for p in places}:
            raise ValueError("Новое место должно примыкать к известному и иметь новый ID.")
        if new.anchor != next(p.anchor for p in places if p.id == new.parent):
            raise ValueError("Новое место не может менять регион скрытым переходом.")
        places.append(new)
    state = replace(before, places=tuple(places))
    witnesses, messages, risky = set(), [], False
    for index, step in enumerate(plan.steps):
        current_things = {t.id: t for t in state.things}
        if step.op in {"look", "inventory"}:
            if step.op == "inventory":
                if step.target not in {"", "hero"}:
                    raise ValueError("Этот запрос не открывает чужой инвентарь.")
                messages.append(state.inventory())
            elif step.target:
                if step.target not in current_things or not state.here(current_things[step.target]):
                    raise ValueError("Нельзя осмотреть отсутствующий предмет.")
                item = current_things[step.target]
                contents = "; ".join(
                    f"{t.name} ×{t.quantity}" for t in state.things if t.holder == item.id
                )
                messages.append(
                    item.name
                    + (
                        ". Содержит: " + (contents or "пусто")
                        if item.container
                        else f" ×{item.quantity}"
                    )
                )
            else:
                messages.append(state.place().name)
            continue
        if step.op == "move":
            if step.target not in {p.id for p in state.places}:
                raise ValueError("Такое место ещё не зарегистрировано.")
            target = state.place(step.target)
            if (
                target.id != state.current
                and target.parent != state.current
                and state.place().parent != target.id
            ):
                raise ValueError("Нужен связный путь: нельзя перескочить через неизвестное место.")
            state = replace(state, current=target.id)
            messages.append("Вы переместились: " + target.name + ".")
            continue
        if step.target not in current_things:
            raise ValueError("Такого предмета нет в известном состоянии мира.")
        item = current_things[step.target]
        quantity = item.quantity if step.quantity == 0 else step.quantity
        if not state.here(item) or quantity > item.quantity:
            raise ValueError("Предмет недоступен здесь или его меньше, чем указано.")
        held = state.root_holder(item)
        if step.op == "take":
            if item.holder == "hero":
                messages.append(item.name + " уже при вас.")
                continue
            guarded = any(a.id == held for a in state.actor_refs) or any(
                a.id in {item.owner, "guard"} and a.place == state.current for a in state.actor_refs
            )
            if held != "hero" and item.owner and item.owner != "hero" and guarded:
                risky = True
                witnesses.update(a.id for a in state.actor_refs if a.place == state.current)
            destination = "hero"
        else:
            if held != "hero":
                raise ValueError("Нельзя выбросить или переложить предмет, которого у вас нет.")
            destination = state.current if step.op == "drop" else step.destination
            if step.op == "give" and (
                not any(a.id == destination and a.place == state.current for a in state.actor_refs)
            ):
                raise ValueError("Получателя здесь нет.")
            if step.op == "put" and (
                destination not in current_things
                or not current_things[destination].container
                or not state.here(current_things[destination])
                or destination == item.id
            ):
                raise ValueError("Контейнер недоступен или не подходит.")
        updated = list(state.things)
        updated.remove(item)
        moved = replace(item, holder=destination, quantity=quantity)
        if step.op == "give" and item.owner == "hero":
            moved = replace(moved, owner=destination)
        if quantity < item.quantity:
            updated.append(replace(item, quantity=item.quantity - quantity))
            moved = replace(moved, id=f"split_{turn_index}_{index}")
        updated.append(moved)
        state = replace(state, things=tuple(updated))
        verb = {
            "take": "Взято",
            "drop": "Оставлено на месте",
            "put": "Переложено",
            "give": "Передано",
        }[step.op]
        messages.append(f"{verb}: {item.name} ×{quantity}.")
    visited = {s.target for s in plan.steps if s.op == "move"}
    if any(p.id not in visited for p in plan.places):
        raise ValueError("Нельзя создавать места, к которым герой не направлялся.")
    if risky and not check_succeeded:
        state = before
        messages = ["Забрать чужой предмет и выполнить цепочку не удалось. Вещи остались на месте."]
    return state, risky, tuple(sorted(witnesses)), tuple(messages)


@dataclass(frozen=True)
class Interaction:
    before: InteractiveWorld
    plan: WorldPlan
    after: InteractiveWorld
    witnesses: tuple[str, ...]
    summary: str
    roll: D20Roll | None = None
    check: AbilityCheck | None = None
    version: str = "interaction-homebrew-1"

    def to_dict(self):
        return asdict(self) | {"before": self.before.to_dict(), "after": self.after.to_dict()}

    @classmethod
    def restore(cls, data, dice, turn_index):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Неверная запись изменения мира.")
        before, plan = InteractiveWorld.from_dict(data["before"]), WorldPlan.from_dict(data["plan"])
        roll = check = None
        if data["roll"] is not None:
            roll = dice.roll_d20()
            if asdict(roll) != data["roll"]:
                raise ValueError("Изменена последовательность кубиков мира.")
            check = resolve_ability_check("dexterity", data["check"]["score"], roll.value, 15)
            if asdict(check) != data["check"]:
                raise ValueError("Неверная проверка завладения предметом.")
        after, risky, witnesses, messages = apply_plan(
            before,
            plan,
            check_succeeded=check.succeeded if check else True,
            turn_index=turn_index,
        )
        if risky != (check is not None) or data["check"] is not None and check is None:
            raise ValueError("Не хватает проверки рискованного действия.")
        record = cls(before, plan, after, witnesses, "\n".join(messages), roll, check)
        if json.loads(json.dumps(record.to_dict())) != json.loads(json.dumps(data)):
            raise ValueError("Изменения мира не соответствуют проверенному плану.")
        return record
