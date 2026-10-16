"""Versioned homebrew creation and a finite, auditable first progression cycle."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.character import ABILITY_NAMES, AbilityCheck, Character

RULES_VERSION = "homebrew-progression-1"
POINT_BUDGET = 24
LEVEL_TWO_XP = 4
TRAINING_STEP = 2
TRAINING_CAP = 20


@dataclass(frozen=True)
class Archetype:
    name: str
    description: str
    scores: tuple[int, ...]
    gold: int
    bandages: int
    equipment: str


ARCHETYPES = {
    "fighter": Archetype(
        "Боец",
        "Путник с учебным мечом и запасом бинтов. Бой пока не реализован.",
        (16, 12, 14, 8, 12, 10),
        8,
        2,
        "Учебный меч",
    ),
    "scout": Archetype(
        "Разведчик",
        "Профиль исследователя дороги. Скрытные атаки пока недоступны.",
        (12, 16, 12, 10, 12, 10),
        10,
        1,
        "Дорожный нож",
    ),
    "scholar": Archetype(
        "Книжник",
        "Любитель обучения. Заклинаний в этом профиле нет.",
        (8, 10, 12, 16, 14, 12),
        9,
        1,
        "Дорожный посох",
    ),
}
ACTIVITIES = {
    "cart": ("помочь разгрузить телегу", "strength", "Разгрузка телеги у ворот"),
    "road": ("исследовать дорогу", "dexterity", "Первое исследование дороги"),
    "book": ("изучить учебник", "intelligence", "Первое изучение дорожного учебника"),
}
PRACTICE_COMMANDS = {"помочь разгрузить телегу", "изучить учебник", "развитие"}


def validate_creation(character: Character, class_id: str) -> None:
    if not isinstance(class_id, str) or class_id not in ARCHETYPES:
        raise ValueError("Выберите один из доступных авторских профилей.")
    scores = [character.score(ability) for ability in ABILITY_NAMES]
    if any(not 8 <= score <= 16 for score in scores):
        raise ValueError("Стартовые характеристики должны быть от 8 до 16.")
    if sum(score - 8 for score in scores) != POINT_BUDGET:
        raise ValueError("Распределите ровно 24 очка; каждое повышение на 1 стоит 1 очко.")


@dataclass(frozen=True)
class DevelopmentEvent:
    activity: str
    turn_index: int
    ability: str
    points: int
    reason: str
    roll_index: int | None
    before_score: int
    after_score: int
    before_level: int
    after_level: int
    max_hp_delta: int
    rules_version: str = RULES_VERSION


@dataclass(frozen=True)
class HeroProgress:
    class_id: str = "legacy"
    initial: Character | None = None
    events: tuple[DevelopmentEvent, ...] = ()

    def __post_init__(self) -> None:
        if self.class_id == "legacy":
            if self.initial is not None or self.events:
                raise ValueError("Legacy sandbox cannot have progression rewards")
        else:
            if not isinstance(self.initial, Character):
                raise ValueError("Missing original created character")
            validate_creation(self.initial, self.class_id)

    @property
    def enabled(self) -> bool:
        return self.class_id != "legacy"

    @property
    def xp(self) -> int:
        return sum(event.points for event in self.events)

    @property
    def level(self) -> int:
        return 2 if self.xp >= LEVEL_TWO_XP else 1

    def practiced(self, activity: str) -> bool:
        return any(event.activity == activity for event in self.events)

    def training(self, ability: str) -> int:
        return sum(event.points for event in self.events if event.ability == ability)

    def character(self) -> Character:
        if self.initial is None:
            raise ValueError("Legacy sandbox has no original creation profile")
        return replace(
            self.initial,
            **{
                ability: min(
                    TRAINING_CAP,
                    self.initial.score(ability) + self.training(ability) // TRAINING_STEP,
                )
                for ability in ABILITY_NAMES
            },
        )

    def award(
        self, activity: str, turn_index: int, check: AbilityCheck | None, roll_index: int | None
    ):
        if not self.enabled or activity not in ACTIVITIES or self.practiced(activity):
            raise ValueError("Activity cannot grant another reward")
        if (
            type(turn_index) is not int
            or turn_index < 1
            or (self.events and turn_index <= self.events[-1].turn_index)
        ):
            raise ValueError("Invalid development event index")
        _, ability, reason = ACTIVITIES[activity]
        if activity == "book":
            if check is not None or roll_index is not None:
                raise ValueError("Book study does not roll dice")
            points = 2
        else:
            if (
                check is None
                or check.ability != ability
                or check.difficulty != 10
                or check.score != self.character().score(ability)
                or type(roll_index) is not int
                or roll_index < 1
            ):
                raise ValueError("Training requires a matching check")
            points = 2 if check.succeeded else 1
        before = self.character().score(ability)
        after = min(
            TRAINING_CAP, self.initial.score(ability) + (self.training(ability) + points) // 2
        )
        after_level = 2 if self.xp + points >= LEVEL_TWO_XP else 1
        event = DevelopmentEvent(
            activity,
            turn_index,
            ability,
            points,
            reason,
            roll_index,
            before,
            after,
            self.level,
            after_level,
            2 if after_level > self.level else 0,
        )
        return replace(self, events=(*self.events, event))

    def to_dict(self) -> dict:
        return {
            "rules_version": RULES_VERSION,
            "class_id": self.class_id,
            "initial": asdict(self.initial) if self.initial is not None else None,
            "events": [asdict(event) for event in self.events],
        }

    @classmethod
    def from_dict(cls, data: object, turns) -> "HeroProgress":
        if (
            not isinstance(data, dict)
            or set(data) != {"rules_version", "class_id", "initial", "events"}
            or data["rules_version"] != RULES_VERSION
            or not isinstance(data["class_id"], str)
            or not isinstance(data["events"], list)
            or len(data["events"]) > len(ACTIVITIES)
        ):
            raise ValueError("Invalid progression structure or rules version")
        initial = None if data["initial"] is None else Character.from_dict(data["initial"])
        result = cls(data["class_id"], initial)
        last_index = 0
        for item in data["events"]:
            if not isinstance(item, dict) or set(item) != set(
                DevelopmentEvent.__dataclass_fields__
            ):
                raise ValueError("Invalid development event")
            integer_keys = (
                "turn_index",
                "points",
                "before_score",
                "after_score",
                "before_level",
                "after_level",
                "max_hp_delta",
            )
            if any(type(item[key]) is not int for key in integer_keys) or (
                item["roll_index"] is not None and type(item["roll_index"]) is not int
            ):
                raise ValueError("Invalid event numbers")
            index = item["turn_index"]
            if not last_index < index <= len(turns) or not isinstance(item["activity"], str):
                raise ValueError("Invalid event order")
            activity = item["activity"]
            if activity not in ACTIVITIES:
                raise ValueError("Unknown activity")
            from rpg_vkr.commands import normalise_action

            turn = turns[index - 1]
            if normalise_action(turn.action) != ACTIVITIES[activity][0]:
                raise ValueError("Development event does not match action")
            if activity == "book" and not turn.text.startswith("Вы изучили учебник."):
                raise ValueError("Book event requires completed study")
            roll_index = turn.roll.index if turn.roll is not None else None
            result = result.award(activity, index, turn.check, roll_index)
            if item != asdict(result.events[-1]):
                raise ValueError("Development event does not match rules")
            last_index = index
        return result


def describe_progress(progress: HeroProgress) -> str:
    if not progress.enabled:
        return "Учебная песочница: развитие отключено. Создайте нового героя с профилем и бюджетом."
    training = "; ".join(
        f"{name}: {progress.training(key)} очк." for key, name in ABILITY_NAMES.items()
    )
    return (
        f"Профиль: {ARCHETYPES[progress.class_id].name}; "
        f"уровень {progress.level}; опыт {progress.xp}. "
        f"Первое повышение при 4 опыте; максимум текущего эпизода — уровень 2.\n"
        f"Обучение (накоплено; каждые 2 очка дают +1 характеристике, до 20): {training}"
    )


def describe_award(event: DevelopmentEvent) -> str:
    text = (
        f"Развитие: {event.reason} — +{event.points} опыта "
        f"и обучения ({ABILITY_NAMES[event.ability]})."
    )
    if event.after_score > event.before_score:
        text += f" Характеристика: {event.before_score} → {event.after_score}."
    if event.after_level > event.before_level:
        text += " Уровень 2! Максимум здоровья +2; текущее здоровье не восполняется."
    return text
