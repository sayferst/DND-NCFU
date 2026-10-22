"""Authored investigation: independent checks and persistent information, no loot/XP."""

import json
import re
from dataclasses import asdict, dataclass

from rpg_vkr.domain.character import AbilityCheck, resolve_ability_check
from rpg_vkr.domain.dice import D20Roll

COMMAND = "исследовать окрестности"
SUPPORTED = {"intelligence", "wisdom", "constitution"}
CLUES = {
    "gate": (
        (
            "По следам телег можно проследить путь через площадь к рынку. "
            "Дорога на рынок теперь известна."
        ),
        (
            "Задержавшись у ворот, вы замечаете, как жители придерживают "
            "корзины на неровной земле: здесь легко рассыпать поклажу."
        ),
    ),
    "road": (
        (
            "На каменистом участке ровная земля идёт ближе к краю. Перед "
            "трудным переходом можно осмотреть эту полосу."
        ),
        (
            "После долгого осмотра различимы обходные следы у гравия: не "
            "все путники выбирают середину дороги."
        ),
    ),
    "market": (
        (
            "По движению покупателей видно, где заканчивается торговый ряд "
            "и принимают доставленные корзины."
        ),
        (
            "Понаблюдав дольше, вы замечаете, что торговец обсуждает товар "
            "у прилавка, а не с дальнего края площади."
        ),
    ),
}


def requested_abilities(text):
    """A bounded offline hint for explicit requests, never arbitrary action execution."""
    text = re.sub(r'«[^»]*»|"[^"]*"|“[^”]*”', "", text.casefold()).replace("ё", "е")
    if re.match(r"\s*(?:цитирую|можно ли|могу ли|спрашиваю|спросить)\b", text):
        return None
    if re.search(r"\b(?:без|не)\s+(?:используя\s+)?(?:интел|мудрост|вынослив|телослож)", text):
        return None
    if not re.match(
        r"\s*(?:я\s+)?(?:(?:хочу|попробую|буду)\s+)?"
        r"(?:(?:внимательно|тщательно|подробно)\s+)?"
        r"(?:осмотреть|осмотрю|осматриваю|огляд|огляж|исследовать окрестности)",
        text,
    ):
        return None
    if not re.search(r"осмотр|осмотре|осматри|огля|окрестност|вокруг|окружени", text):
        return None
    if re.search(
        r"\b(?:не осмат|не исслед|атак|удар|куп|прод|забер|возьм|сожг|пойду|пойти|вернусь)\w*|;",
        text,
    ):
        return None
    matches = []
    for ability, pattern in (
        ("intelligence", r"интел+ект\w*"),
        ("wisdom", r"мудрост\w*|внимательност\w*"),
        ("constitution", r"вынослив\w*|телослож\w*"),
    ):
        match = re.search(pattern, text)
        if match:
            matches.append((match.start(), ability))
    if matches:
        return tuple(ability for _, ability in sorted(matches))
    if re.search(r"внимательно|тщательно|подробно|исследовать окрестности", text):
        return ("intelligence",)
    return None


@dataclass(frozen=True)
class InspectionCheck:
    roll: D20Roll
    check: AbilityCheck


@dataclass(frozen=True)
class Inspection:
    location: str
    checks: tuple[InspectionCheck, ...]
    route_known_before: bool
    version: str = "inspection-homebrew-1"

    def __post_init__(self):
        if self.location not in CLUES or type(self.route_known_before) is not bool:
            raise ValueError("Invalid investigation context")
        if self.version != "inspection-homebrew-1" or not 1 <= len(self.checks) <= 3:
            raise ValueError("Invalid investigation version/check count")
        abilities = []
        for item in self.checks:
            if not isinstance(item, InspectionCheck) or item.check.ability not in SUPPORTED:
                raise ValueError("Invalid investigation ability")
            expected = resolve_ability_check(
                item.check.ability, item.check.score, item.roll.value, 10
            )
            if item.check != expected or type(item.roll.index) is not int or item.roll.index < 1:
                raise ValueError("Investigation calculation mismatch")
            abilities.append(item.check.ability)
        if len(abilities) != len(set(abilities)):
            raise ValueError("Duplicate investigation check")

    @property
    def abilities(self):
        return tuple(item.check.ability for item in self.checks)

    @property
    def rolls(self):
        return tuple(item.roll for item in self.checks)

    @property
    def deductions(self):
        return any(
            item.check.succeeded and item.check.ability != "constitution" for item in self.checks
        )

    @property
    def sustained(self):
        return any(
            item.check.succeeded and item.check.ability == "constitution" for item in self.checks
        )

    @property
    def clues(self):
        if not self.deductions:
            return ()
        return CLUES[self.location][: 2 if self.sustained else 1]

    @property
    def reveals_route(self):
        return self.location == "gate" and self.deductions and not self.route_known_before

    def story(self):
        if self.clues:
            result = "Осмотр помог разобраться в деталях.\n" + "\n".join(self.clues)
        else:
            result = "Вы исследуете окрестности, но пока не находите новых убедительных зацепок."
        constitution = next(
            (item for item in self.checks if item.check.ability == "constitution"), None
        )
        if constitution:
            result += (
                "\nВы сохраняете внимание во время долгого поиска."
                if constitution.check.succeeded
                else "\nДолгий поиск утомляет; дополнительный осмотр не приносит новых наблюдений."
            )
        return result

    def to_dict(self):
        return asdict(self)

    @classmethod
    def restore(cls, data, dice):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid saved investigation")
        if not isinstance(data["checks"], (list, tuple)) or not 1 <= len(data["checks"]) <= 3:
            raise ValueError("Invalid investigation checks")
        checks = []
        for raw in data["checks"]:
            if not isinstance(raw, dict) or set(raw) != {"roll", "check"}:
                raise ValueError("Invalid investigation roll")
            roll = dice.roll_d20()
            check = AbilityCheck(**raw["check"])
            if raw["roll"] != asdict(roll):
                raise ValueError("Investigation RNG history mismatch")
            checks.append(InspectionCheck(roll, check))
        result = cls(data["location"], tuple(checks), data["route_known_before"], data["version"])
        if json.dumps(result.to_dict(), sort_keys=True) != json.dumps(data, sort_keys=True):
            raise ValueError("Investigation data types differ from canonical record")
        return result


def inspect(world, character, dice, abilities):
    if not isinstance(abilities, tuple) or not abilities or len(abilities) != len(set(abilities)):
        raise ValueError("Invalid requested checks")
    if any(ability not in SUPPORTED for ability in abilities) or len(abilities) > 3:
        raise ValueError("Unsupported inspection ability")
    checks = []
    for ability in abilities:
        roll = dice.roll_d20()
        checks.append(
            InspectionCheck(
                roll, resolve_ability_check(ability, character.score(ability), roll.value, 10)
            )
        )
    return Inspection(world.location, tuple(checks), world.market_known)
