"""A demo character and the implemented subset of SRD 5.2.1 ability checks."""

from dataclasses import dataclass

ABILITY_NAMES = {
    "strength": "Сила",
    "dexterity": "Ловкость",
    "constitution": "Телосложение",
    "intelligence": "Интеллект",
    "wisdom": "Мудрость",
    "charisma": "Харизма",
}


def ability_modifier(score: int) -> int:
    if type(score) is not int or not 1 <= score <= 30:
        raise ValueError("Ability score must be an integer in 1..30")
    return (score - 10) // 2


@dataclass(frozen=True)
class Character:
    name: str = "Путник"
    strength: int = 14
    dexterity: int = 12
    constitution: int = 13
    intelligence: int = 10
    wisdom: int = 15
    charisma: int = 8

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 40:
            raise ValueError("Invalid character name")
        for ability in ABILITY_NAMES:
            ability_modifier(self.score(ability))

    def score(self, ability: str) -> int:
        if ability not in ABILITY_NAMES:
            raise ValueError("Unknown ability")
        return getattr(self, ability)

    @classmethod
    def from_dict(cls, data: object) -> "Character":
        if not isinstance(data, dict) or set(data) != {"name", *ABILITY_NAMES}:
            raise ValueError("Invalid character structure")
        return cls(**data)


@dataclass(frozen=True)
class AbilityCheck:
    ability: str
    score: int
    difficulty: int
    modifier: int
    total: int
    succeeded: bool


def resolve_ability_check(ability: str, score: int, die: int, difficulty: int) -> AbilityCheck:
    if ability not in ABILITY_NAMES:
        raise ValueError("Unknown ability")
    modifier = ability_modifier(score)
    if type(die) is not int or not 1 <= die <= 20:
        raise ValueError("A d20 result must be in 1..20")
    if type(difficulty) is not int or not 1 <= difficulty <= 30:
        raise ValueError("Implemented difficulty range is 1..30")
    total = die + modifier
    return AbilityCheck(ability, score, difficulty, modifier, total, total >= difficulty)


def describe_check(check: AbilityCheck, die: int) -> str:
    outcome = "успех" if check.succeeded else "неудача"
    return (
        f"{ABILITY_NAMES[check.ability]}: d20 ({die}) {check.modifier:+d} = {check.total}; "
        f"сложность {check.difficulty} — {outcome}."
    )
