"""Versioned, original homebrew catalogs; external corpus cards are never executable rules."""

from copy import deepcopy
from dataclasses import replace

from rpg_vkr.domain import gameplay as base
from rpg_vkr.domain import gameplay_v4 as previous
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.interactions import label

SPECIES = {
    "human": ("Человек", "charisma", "Общительность: +1 Харизма"),
    "elf": ("Эльф", "intelligence", "Сосредоточенность: +1 Интеллект"),
    "dwarf": ("Дворф", "constitution", "Стойкость: +1 Телосложение"),
    "orc": ("Орк", "strength", "Сила: +1 Сила"),
    "halfling": ("Полурослик", "dexterity", "Проворство: +1 Ловкость"),
}
KITS = {
    "melee": ("Ближний бой", "sword", ("iron", "iron", "cloth")),
    "ranged": ("Дальний бой", "longbow", ("herb", "cloth", "cloth")),
    "support": ("Поддержка", "dagger", ("herb", "herb", "cloth")),
    "artisan": ("Мастер", "dagger", ("iron", "iron", "cloth", "herb")),
}
ABILITIES = {
    "warrior": ("Второе дыхание", "hp", 5),
    "ranger": ("Полевой привал", "st", 6),
    "mage": ("Сосредоточение", "mp", 5),
    "healer": ("Целительское прикосновение", "hp", 7),
    "artisan": ("Рабочий ритм", "st", 7),
    "free": ("Собраться с силами", "st", 5),
}
SPELLS = {}
for circle in range(1, 6):
    for school, name, effect, cost in (
        ("elemental", "Стихийный разряд", "attack", 3),
        ("restoration", "Живительная сила", "heal", 4),
        ("protection", "Магический покров", "ward", 3),
        ("utility", "Путеводный свет", "light", 1),
    ):
        SPELLS[f"{school}_{circle}"] = {
            "name": f"{name} {circle}",
            "school": school,
            "circle": circle,
            "mp": cost + 4 * (circle - 1),
            "effect": effect,
            "dice": f"{circle}d6",
            "range": 12 + 3 * circle,
            "duration": (10 if effect == "ward" else 60) * circle,
            "components": max(0, circle - 1),
            "rank": circle,
            "level": 1 + 4 * (circle - 1),
        }
# Existing six spells remain available with their original costs and behavior.
ITEMS = dict(
    base.ITEM_NAMES,
    wood="Древесина",
    ingot="Слиток",
    potion="Лечебное зелье",
    meal="Походная еда",
    crystal="Магический кристалл",
    forge="Переносная кузница",
    lab="Алхимическая лаборатория",
    loom="Ткацкий станок",
)
PRICES = dict(
    base.PRICES, wood=10, ingot=60, potion=120, meal=30, crystal=100, forge=300, lab=300, loom=200
)
RECIPES = {
    "ingot": {
        "name": "Выплавить слиток",
        "inputs": {"iron": 2, "wood": 1},
        "station": "forge",
        "skill": "smithing",
        "rank": 1,
        "minutes": 30,
        "output": "ingot",
    },
    "sword": {
        "name": "Выковать меч",
        "inputs": {"ingot": 2, "wood": 1},
        "station": "forge",
        "skill": "smithing",
        "rank": 2,
        "minutes": 60,
        "output": "sword",
    },
    "mail": {
        "name": "Сплести кольчугу",
        "inputs": {"ingot": 3, "cloth": 2},
        "station": "forge",
        "skill": "smithing",
        "rank": 3,
        "minutes": 120,
        "output": "mail",
    },
    "cloth": {
        "name": "Соткать полотно",
        "inputs": {"herb": 2},
        "station": "loom",
        "skill": "repair",
        "rank": 1,
        "minutes": 20,
        "output": "cloth",
    },
    "potion": {
        "name": "Сварить зелье",
        "inputs": {"herb": 2},
        "station": "lab",
        "skill": "alchemy",
        "rank": 1,
        "minutes": 30,
        "output": "potion",
    },
    "crystal": {
        "name": "Огранить кристалл",
        "inputs": {"ingot": 1, "herb": 2},
        "station": "lab",
        "skill": "arcana",
        "rank": 2,
        "minutes": 60,
        "output": "crystal",
    },
    "meal": {
        "name": "Приготовить еду",
        "inputs": {"herb": 1, "wood": 1},
        "station": "tools",
        "skill": "survival",
        "rank": 0,
        "minutes": 15,
        "output": "meal",
    },
    "forge": {
        "name": "Собрать кузницу",
        "inputs": {"iron": 3, "wood": 2},
        "station": "tools",
        "skill": "smithing",
        "rank": 1,
        "minutes": 60,
        "output": "forge",
    },
    "lab": {
        "name": "Собрать лабораторию",
        "inputs": {"iron": 1, "wood": 2, "cloth": 1},
        "station": "tools",
        "skill": "alchemy",
        "rank": 1,
        "minutes": 60,
        "output": "lab",
    },
    "loom": {
        "name": "Собрать станок",
        "inputs": {"wood": 3, "iron": 1},
        "station": "tools",
        "skill": "repair",
        "rank": 1,
        "minutes": 45,
        "output": "loom",
    },
}


def identity(value):
    value = deepcopy(value)
    value.setdefault(
        "kit",
        {"warrior": "melee", "ranger": "ranged", "artisan": "artisan"}.get(
            value.get("profile"), "support"
        ),
    )
    value.setdefault("starting_spells", [])
    if value["kit"] not in KITS or not isinstance(value["starting_spells"], list):
        raise ValueError("Выберите стартовый набор и список заклинаний.")
    spells = value["starting_spells"]
    if (
        len(spells) > 2
        or any(not isinstance(s, str) for s in spells)
        or len(set(spells)) != len(spells)
    ):
        raise ValueError("Можно выбрать до двух различных начальных заклинаний.")
    if any(s not in SPELLS or SPELLS[s]["circle"] != 1 for s in spells):
        raise ValueError("Начальные заклинания должны принадлежать I кругу.")
    if spells and value.get("skills", {}).get("arcana", 0) < 1:
        raise ValueError("Для начальной магии нужен ранг Теории магии1.")
    old = {k: v for k, v in value.items() if k not in {"kit", "starting_spells"}}
    previous.initial(old, Character())
    return value


def inherited(character, state):
    key = SPECIES[state["identity"]["species"]][1]
    return replace(character, **{key: min(20, getattr(character, key) + 1)})


def make_item(id, kind, owner="hero", quality=1):
    if kind not in ITEMS or type(quality) is not int or not 1 <= quality <= 3:
        raise ValueError("Неверный предмет или качество.")
    label(id, 100)
    return {
        "id": id,
        "kind": kind,
        "owner": owner,
        "durability": 20,
        "name": ITEMS[kind],
        "price_cp": PRICES[kind] * quality,
        "quality": quality,
    }


def spell_rows():
    result = dict(base.SPELLS)
    result.update(
        {
            key: (
                s["name"],
                s["circle"],
                s["mp"],
                s["effect"],
                s["dice"],
                s["range"],
                s["components"],
            )
            for key, s in SPELLS.items()
        }
    )
    return result


ITEMS["rune"] = "Защитная руна"
PRICES["rune"] = 180
RECIPES["rune"] = {
    "name": "Начертать защитную руну",
    "inputs": {"crystal": 1, "cloth": 1},
    "station": "lab",
    "skill": "arcana",
    "rank": 3,
    "minutes": 60,
    "output": "rune",
}

ITEMS["legacy_object"] = "Сохранённый предмет"
PRICES["legacy_object"] = 0
