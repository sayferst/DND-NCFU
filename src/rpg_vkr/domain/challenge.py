"""Confirmed checks for bounded free-form attempts; no implicit resource effects."""

import re
from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.character import AbilityCheck, resolve_ability_check
from rpg_vkr.domain.dice import D20Roll

# Difficulty/category selection is authored homebrew; d20 + modifier follows SRD.
CHALLENGES = {
    "effort": ("strength", 15, "приложить физическое усилие"),
    "climb": ("strength", 15, "найти опору и удержаться при подъёме"),
    "acrobatics": ("dexterity", 15, "точно рассчитать движение и сохранить равновесие"),
    "endure": ("constitution", 15, "выдержать нагрузку или воздействие среды"),
    "decipher": ("intelligence", 15, "разобраться в смысле надписи или загадки"),
    "recall": ("intelligence", 10, "вспомнить подходящие сведения"),
    "listen": ("wisdom", 10, "различить детали звуков вокруг"),
    "persuade": ("charisma", 15, "ясно и убедительно изложить доводы"),
}

CHALLENGE_SKILLS = {
    "effort": "athletics",
    "climb": "athletics",
    "acrobatics": "acrobatics",
    "decipher": "knowledge",
    "recall": "knowledge",
    "listen": "perception",
    "persuade": "persuasion",
}


def validate_assessment(value):
    from rpg_vkr.domain.campaign import plain
    from rpg_vkr.domain.character import ABILITY_NAMES

    if not isinstance(value, dict) or set(value) not in (
        {"ability", "dc", "purpose"},
        {"ability", "dc", "purpose", "skill"},
    ):
        raise ValueError("Неверное предложение общей проверки.")
    if (
        value["ability"] not in ABILITY_NAMES
        or type(value["dc"]) is not int
        or not 5 <= value["dc"] <= 25
    ):
        raise ValueError("Неизвестная характеристика или сложность вне 5–25.")
    plain(value["purpose"], 400)
    if "skill" in value:
        from rpg_vkr.domain.d20_progression import SKILLS

        if (
            not isinstance(value["skill"], str)
            or value["skill"] not in SKILLS
            or SKILLS[value["skill"]][1] != value["ability"]
        ):
            raise ValueError("Навык не соответствует характеристике.")
    return value


@dataclass(frozen=True)
class Challenge:
    kind: str
    location: str
    roll: D20Roll
    check: AbilityCheck
    version: str = "challenge-homebrew-1"
    assessment: dict | None = None

    def __post_init__(self):
        from rpg_vkr.domain.world import LOCATIONS

        if (
            self.kind not in CHALLENGES and self.kind != "general"
        ) or self.location not in LOCATIONS:
            raise ValueError("Unknown challenge")
        if self.version not in {
            "challenge-homebrew-1",
            "challenge-homebrew-2",
            "challenge-homebrew-3",
        }:
            raise ValueError("Unknown challenge version")
        skill_bonus = 0
        if self.version == "challenge-homebrew-3":
            from rpg_vkr.domain.d20_progression import SKILLS

            spec = self.assessment
            if not isinstance(spec, dict) or set(spec) != {
                "ability",
                "dc",
                "purpose",
                "skill",
                "rank",
                "revision",
            }:
                raise ValueError("Неверная запись проверки навыка.")
            validate_assessment({k: spec[k] for k in ("ability", "dc", "purpose")})
            if (
                not isinstance(spec["skill"], str)
                or spec["skill"] not in SKILLS
                or type(spec["rank"]) is not int
                or not 0 <= spec["rank"] <= 5
                or type(spec["revision"]) is not int
                or not 0 <= spec["revision"] <= 4096
                or SKILLS[spec["skill"]][1] != spec["ability"]
                or self.kind != "general"
                and CHALLENGE_SKILLS.get(self.kind) != spec["skill"]
            ):
                raise ValueError("Навык не подходит к проверке.")
            ability, difficulty = spec["ability"], spec["dc"]
            skill_bonus = 2 * spec["rank"]
        elif self.version == "challenge-homebrew-2":
            spec = validate_assessment(self.assessment)
            if "skill" in spec:
                raise ValueError("Навык требует новую версию проверки.")
            if self.kind != "general":
                raise ValueError("Неверная категория общей проверки.")
            ability, difficulty = spec["ability"], spec["dc"]
        else:
            if self.kind not in CHALLENGES or self.assessment is not None:
                raise ValueError("Legacy challenge schema changed")
            ability, difficulty, _ = CHALLENGES[self.kind]
        if (
            not isinstance(self.check, AbilityCheck)
            or any(
                type(getattr(self.check, key)) is not int
                for key in ("score", "difficulty", "modifier", "total")
            )
            or type(self.check.succeeded) is not bool
        ):
            raise ValueError("Invalid challenge check types")
        if (
            not isinstance(self.roll, D20Roll)
            or type(self.roll.index) is not int
            or self.roll.index < 1
        ):
            raise ValueError("Invalid challenge roll")
        expected = resolve_ability_check(ability, self.check.score, self.roll.value, difficulty)
        if skill_bonus:
            expected = replace(
                expected,
                modifier=expected.modifier + skill_bonus,
                total=expected.total + skill_bonus,
                succeeded=expected.total + skill_bonus >= difficulty,
            )
        if asdict(self.check) != asdict(expected):
            raise ValueError("Challenge calculation mismatch")

    def story(self):
        purpose = self.assessment["purpose"] if self.assessment else CHALLENGES[self.kind][2]
        result = "Проверка удалась" if self.check.succeeded else "Проверка не удалась"
        text = f"{result}: {purpose}."
        if self.version == "challenge-homebrew-3":
            from rpg_vkr.domain.d20_progression import SKILLS

            text += (
                f" {SKILLS[self.assessment['skill']][0]}: ранг {self.assessment['rank']}, "
                f"бонус +{2 * self.assessment['rank']}."
            )
        return text

    def to_dict(self):
        value = asdict(self)
        if self.version == "challenge-homebrew-1":
            value.pop("assessment")
        return value

    @classmethod
    def restore(cls, data, dice):
        if not isinstance(data, dict) or set(data) != (
            set(cls.__dataclass_fields__)
            if data.get("version") in {"challenge-homebrew-2", "challenge-homebrew-3"}
            else set(cls.__dataclass_fields__) - {"assessment"}
        ):
            raise ValueError("Invalid challenge record")
        if not isinstance(data["roll"], dict) or any(
            type(data["roll"].get(key)) is not int for key in ("index", "value")
        ):
            raise ValueError("Invalid stored challenge roll")
        roll = dice.roll_d20()
        if data["roll"] != asdict(roll):
            raise ValueError("Challenge RNG mismatch")
        result = cls(
            data["kind"],
            data["location"],
            roll,
            AbilityCheck(**data["check"]),
            data["version"],
            data.get("assessment"),
        )
        if result.to_dict() != data:
            raise ValueError("Challenge record mismatch")
        return result


def proposed_challenge(text):
    """Recognize explicit attempts only. Questions, quotes and extra actions do not roll."""
    from rpg_vkr.narrative.actions import ATTACK
    from rpg_vkr.narrative.speech import unquoted

    value = unquoted(text)
    if (
        "?" in text
        or re.search(ATTACK, value)
        or re.search(
            r"\b(?:не|если|без|цитирую|говорю|сказал|спрашиваю|можно|могу|купить|куплю|"
            r"продать|продам|забрать|заберу|украсть|получить|убить|убью|телепорт|колдую)\w*\b",
            value,
        )
        or re.search(r"[;\n]|\b(?:затем|потом|после этого)\b", value)
    ):
        return None
    value = re.sub(r"^(?:я\s+)?(?:(?:хочу|пытаюсь|попробую|решаю)\s+)?", "", value)
    for kind, pattern in (
        ("climb", r"(?:взобраться|взберусь|взбираюсь|залезть|залезаю|карабкаюсь)\b"),
        ("effort", r"(?:поднять|подниму|поднимаю|сдвинуть|сдвигаю|толкнуть|толкаю|выбить)\b"),
        ("acrobatics", r"(?:перепрыгнуть|перепрыгну|перепрыгиваю|балансировать)\b"),
        ("endure", r"(?:выдержать|выдерживаю|вытерпеть|терплю|перенести)\b"),
        ("decipher", r"(?:расшифровать|расшифровываю|разгадать|разгадываю)\b"),
        ("recall", r"(?:вспомнить|вспоминаю|припомнить)\b"),
        ("listen", r"(?:прислушаться|прислушаюсь|прислушиваюсь)\b"),
        ("persuade", r"(?:убедить|убеждаю|уговорить|уговариваю)\b"),
    ):
        if re.match(pattern, value):
            # A second finite/infinitive action needs its own adjudication.
            if re.search(r"\bи\s+(?:[а-я]+(?:ть|ю|усь)|пойду|возьму|заберу)\b", value):
                return None
            return kind
    return None


def needs_model_review(text):
    """A gate for interpretation, never evidence that an action has happened."""
    from rpg_vkr.narrative.speech import unquoted

    value = unquoted(text)
    if (
        "?" in text
        or any(mark in text for mark in ("«", "»", '"', "“", "”"))
        or re.search(
            r"\b(?:не|если|цитирую|говорю|сказал|спрашиваю|можно|могу|сказать|рассказать)\b",
            value,
        )
    ):
        return False
    return bool(
        re.match(r"(?:я\s+)?(?:пытаюсь|попробую|попытаюсь|хочу|решаю|буду|[а-яё]+ть)\b", value)
    )


def parse_suggestion(data):
    import json

    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise ValueError("Нет предложения проверки")
    message = data["message"]
    if message.get("role") != "assistant":
        raise ValueError("Неверная роль предложения проверки")
    value = json.loads(message.get("content", ""))
    if (
        not isinstance(value, dict)
        or set(value) != {"category"}
        or not isinstance(value["category"], str)
        or value["category"] not in {"none", *CHALLENGES}
    ):
        raise ValueError("Неизвестная категория проверки")
    return value["category"]
