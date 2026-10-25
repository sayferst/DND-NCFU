"""Conservative local spell/workshop commands; negation and conditions never execute."""

import re

from rpg_vkr.domain.gameplay import RECIPES, SPELLS

SPELL_NAMES = {
    "искру": "spark",
    "искра": "spark",
    "исцеление": "mend",
    "защиту": "ward",
    "защита": "ward",
    "свет": "light",
    "пламя": "flame",
    "восстановление": "restore",
}


def parse(text):
    value = text.casefold().strip().rstrip(".! ")
    if re.search(r"\b(?:не|если|когда|сказал|говорю|хочу|могу)\b", value):
        return None
    if value in {"отдохнуть", "отдых 8 часов"}:
        return "rest", {}
    match = re.fullmatch(r"(?:ждать|подождать) (\d{1,5}) (?:минут|минуту|минуты)", value)
    if match:
        return "wait", {"minutes": int(match[1])}
    match = re.fullmatch(r"(?:выучить|изучить) (.+)", value)
    if match and match[1] in SPELL_NAMES:
        return "learn", {"spell": SPELL_NAMES[match[1]]}
    match = re.fullmatch(r"(?:применить|сотворить) (.+)", value)
    if match and match[1] in SPELL_NAMES:
        key = SPELL_NAMES[match[1]]
        if SPELLS[key][3] != "attack":
            return "cast", {"spell": key, "target": "hero"}
    match = re.fullmatch(r"(?:создать|изготовить) (кинжал|бинт)", value)
    if match:
        key = "dagger" if match[1] == "кинжал" else "bandage"
        if key in RECIPES:
            return "craft", {"recipe": key}
    return None
