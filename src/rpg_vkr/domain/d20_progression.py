"""New homebrew rules, isolated from legacy campaign progression and rewards.

This module does not authorize rewards: callers must supply a confirmed engine
achievement. The narrator must never call grant_xp from a prose claim.
"""

import re
from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.character import ability_modifier

RULESET_ID = "dnd-ncfu-homebrew-d20-v1"
SKILL_BONUS_PER_RANK = 2
SKILLS = {
    "athletics": ("Атлетика", "strength"),
    "acrobatics": ("Акробатика", "dexterity"),
    "stealth": ("Скрытность", "dexterity"),
    "perception": ("Внимательность", "wisdom"),
    "survival": ("Выживание", "wisdom"),
    "knowledge": ("Знания", "intelligence"),
    "persuasion": ("Убеждение", "charisma"),
    "trade": ("Торговля", "charisma"),
    "smithing": ("Кузнечное дело", "intelligence"),
    "alchemy": ("Алхимия", "intelligence"),
    "arcana": ("Теория магии", "intelligence"),
    "repair": ("Ремонт", "intelligence"),
}


def required_xp(level):
    if type(level) is not int or not 1 <= level <= 20:
        raise ValueError("Уровень должен быть от 1 до 20.")
    return 50 * (level - 1) * level


def level_for_xp(xp):
    if type(xp) is not int or not 0 <= xp <= 1000000:
        raise ValueError("Недопустимое значение опыта.")
    return max(level for level in range(1, 21) if xp >= required_xp(level))


def rank_limit(level):
    required_xp(level)
    return 2 if level < 5 else 3 if level < 10 else 4 if level < 15 else 5


@dataclass(frozen=True)
class ProgressEvent:
    kind: str
    event_id: str
    subject: str
    amount: int
    reason: str

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in {"xp", "skill"}:
            raise ValueError("Неизвестное событие развития.")
        if not isinstance(self.event_id, str) or not re.fullmatch(
            r"[a-zA-Z0-9_:-]{1,96}", self.event_id
        ):
            raise ValueError("Недопустимый идентификатор события.")
        if not isinstance(self.subject, str) or not isinstance(self.reason, str):
            raise ValueError("Неверные данные события.")
        if (
            not self.reason.strip()
            or len(self.reason) > 200
            or any(ord(c) < 32 for c in self.reason)
        ):
            raise ValueError("Нужна краткая причина развития.")
        if type(self.amount) is not int or not 1 <= self.amount <= 19000:
            raise ValueError("Неверное число очков.")


@dataclass(frozen=True)
class D20Progress:
    events: tuple[ProgressEvent, ...] = ()

    def __post_init__(self):
        self._replay()

    def _replay(self):
        if not isinstance(self.events, tuple) or len(self.events) > 4096:
            raise ValueError("Неверный журнал развития.")
        xp, spent, ranks, ids = 0, 0, {}, set()
        for event in self.events:
            if not isinstance(event, ProgressEvent) or event.event_id in ids:
                raise ValueError("Повторное или неверное событие развития.")
            ids.add(event.event_id)
            if event.kind == "xp":
                if event.subject != "hero":
                    raise ValueError("Опыт относится к герою.")
                xp += event.amount
                level_for_xp(xp)
            else:
                if event.subject not in SKILLS:
                    raise ValueError("Неизвестный навык.")
                rank = ranks.get(event.subject, 0) + 1
                level = level_for_xp(xp)
                if rank > rank_limit(level) or event.amount != rank:
                    raise ValueError("Ранг недоступен или неверна его стоимость.")
                spent += event.amount
                if spent > 13 + 2 * (level - 1):
                    raise ValueError("Недостаточно очков навыков.")
                ranks[event.subject] = rank
        return xp, spent, ranks

    @property
    def xp(self):
        return self._replay()[0]

    @property
    def level(self):
        return level_for_xp(self.xp)

    @property
    def skill_points(self):
        xp, spent, _ = self._replay()
        return 13 + 2 * (level_for_xp(xp) - 1) - spent

    @property
    def attribute_rewards(self):
        return self.level // 4

    @property
    def talent_rewards(self):
        return 1 + self.level // 5

    def rank(self, skill):
        if skill not in SKILLS:
            raise ValueError("Неизвестный навык.")
        return self._replay()[2].get(skill, 0)

    def bonus(self, skill):
        return SKILL_BONUS_PER_RANK * self.rank(skill)

    def grant_xp(self, achievement_id, amount, reason):
        event = ProgressEvent("xp", achievement_id, "hero", amount, reason)
        return replace(self, events=(*self.events, event))

    def train(self, skill, event_id):
        event = ProgressEvent("skill", event_id, skill, self.rank(skill) + 1, "Обучение навыку")
        return replace(self, events=(*self.events, event))

    def to_dict(self):
        return {"ruleset_id": RULESET_ID, "events": [asdict(e) for e in self.events]}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"ruleset_id", "events"}:
            raise ValueError("Неверный формат развития D20.")
        if value["ruleset_id"] != RULESET_ID or not isinstance(value["events"], list):
            raise ValueError("Неизвестная версия правил развития.")
        if len(value["events"]) > 4096:
            raise ValueError("Слишком много событий развития.")
        fields = set(ProgressEvent.__dataclass_fields__)
        if any(not isinstance(e, dict) or set(e) != fields for e in value["events"]):
            raise ValueError("Неверное событие развития.")
        return cls(tuple(ProgressEvent(**e) for e in value["events"]))


@dataclass(frozen=True)
class SkillCheck:
    skill: str
    die: int
    ability_bonus: int
    skill_bonus: int
    equipment_bonus: int
    situational_bonus: int
    difficulty: int
    total: int
    succeeded: bool


def resolve_skill_check(progress, skill, score, die, difficulty, *, equipment=0, situational=0):
    if type(die) is not int or not 1 <= die <= 20:
        raise ValueError("Нужен результат D20 от 1 до 20.")
    if type(difficulty) is not int or not 1 <= difficulty <= 40:
        raise ValueError("Неверная сложность проверки.")
    if any(type(v) is not int or not -20 <= v <= 20 for v in (equipment, situational)):
        raise ValueError("Неверные дополнительные бонусы.")
    ability = ability_modifier(score)
    skill_bonus = progress.bonus(skill)
    total = die + ability + skill_bonus + equipment + situational
    return SkillCheck(
        skill,
        die,
        ability,
        skill_bonus,
        equipment,
        situational,
        difficulty,
        total,
        total >= difficulty,
    )
