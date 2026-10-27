"""Immutable, typed game data and honest coverage counts for the active catalog."""

import hashlib
import json
from collections import Counter
from functools import lru_cache

from rpg_vkr.domain.catalog_authoring import CLASSES, MODES, PROFILES, WEAPONS
from rpg_vkr.domain.interactions import identifier, label
from rpg_vkr.resources import resource_path

EFFECTS = {
    "damage",
    "burn",
    "slow",
    "weaken",
    "stagger",
    "leech",
    "disarm",
    "bleed",
    "mark",
    "shield",
    "anchor",
    "defence",
    "ranged_guard",
    "resist",
    "restore_st",
    "clarity",
    "haste",
    "reflect",
    "heal",
    "cure_bleed",
    "cure_burn",
    "restore_mp",
    "revive",
    "regenerate",
    "cure_poison",
    "cure_weaken",
    "light",
    "perception",
    "reveal_items",
    "reveal_actors",
    "appraise",
    "craft",
    "reveal_nodes",
    "reveal_routes",
    "dispel",
    "accuracy",
    "power",
    "repair",
    "conceal",
    "travel",
    "drain_mp",
}
KINDS = {
    "material",
    "weapon",
    "armour",
    "spell",
    "talent",
    "consumable",
    "household",
    "recipe",
    "creature",
    "event",
}


def validate(data):
    if data.get("schema") != "game-catalog-1" or not isinstance(data.get("records"), list):
        raise ValueError("Неверная схема каталога.")
    rows = data["records"]
    ids, signatures, counts = set(), set(), Counter()
    for row in rows:
        identifier(row["id"])
        label(row["name"], 120)
        label(row["description"], 500)
        if row["id"] in ids or row["kind"] not in KINDS:
            raise ValueError("Повтор ID или неизвестная категория.")
        ids.add(row["id"])
        if any(e["op"] not in EFFECTS or not 1 <= e["power"] <= 20 for e in row.get("effects", [])):
            raise ValueError("Неподдерживаемый эффект.")
        if "mode" in row and row["mode"] not in MODES:
            raise ValueError("Неподдерживаемая форма применения.")
        for key in (
            "level",
            "price_cp",
            "mass_g",
            "mp",
            "cost_st",
            "duration",
            "minutes",
            "cooldown",
            "hp",
            "money",
            "amount",
        ):
            if key in row and (type(row[key]) is not int or not 0 <= row[key] <= 100000):
                raise ValueError("Неверное число: " + key)
        if row.get("level", 1) > 20:
            raise ValueError("Требование уровня выше 20.")
        if (
            row["kind"] == "spell"
            and not {
                "school",
                "circle",
                "mp",
                "range",
                "effects",
                "dice",
                "duration",
                "target_limit",
                "limitations",
                "acquire",
            }
            <= row.keys()
        ):
            raise ValueError("Неполное заклинание.")
        if (
            row["kind"] == "recipe"
            and not {
                "outputs",
                "ingredients",
                "tools",
                "station",
                "minutes",
                "dc",
                "task",
                "failure",
                "quality_cap",
            }
            <= row.keys()
        ):
            raise ValueError("Неполный рецепт.")
        if row["kind"] == "talent" and row["class_id"] not in CLASSES:
            raise ValueError("Неизвестный класс таланта.")
        if row["kind"] == "weapon" and row["category"] not in WEAPONS:
            raise ValueError("Неизвестное оружие.")
        signature = json.dumps(
            {k: v for k, v in row.items() if k not in {"id", "name", "description"}}, sort_keys=True
        )
        if signature in signatures:
            raise ValueError("Декоративный дубль: " + row["id"])
        signatures.add(signature)
        counts[row["kind"] + "/" + row["category"]] += 1
        if row["kind"] == "spell":
            counts["school/" + row["school"]] += 1
    required = {
        *("spell/" + g for g in PROFILES),
        *("talent/" + c for c in CLASSES),
        *("weapon/" + f for f in WEAPONS),
        *("recipe/" + r for r in ("smithing", "alchemy", "repair", "production")),
        *("armour/" + a for a in ("light", "medium", "heavy", "shield")),
        *("consumable/" + c for c in ("potions", "dressings", "scrolls", "ammunition")),
        *("creature/" + c for c in ("beast", "humanoid", "undead", "arcane")),
        *("event/" + e for e in ("economic", "political", "social", "military", "natural")),
        "material/materials",
        "household/household",
    }
    if any(counts[k] < 80 for k in required) or any(n < 80 for n in counts.values()):
        raise ValueError("Категория содержит меньше 80 элементов.")
    for row in rows:
        refs = row.get("outputs", []) + list(row.get("ingredients", {}))
        refs += [row[k] for k in ("material", "spell_id", "resource") if k in row]
        if any(ref not in ids for ref in refs):
            raise ValueError("Битая ссылка: " + row["id"])
    return {
        "total": len(rows),
        "categories": dict(sorted(counts.items())),
        "unique_signatures": len(signatures),
    }


@lru_cache(maxsize=1)
def load():
    path = resource_path("data/gameplay/catalog-v1.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate(data)
    return {r["id"]: r for r in data["records"]}


def row(id, kind=None):
    value = load().get(id)
    if value is None or kind and value["kind"] != kind:
        raise ValueError("Неизвестная запись каталога: " + str(id))
    return value


def digest():
    return hashlib.sha256(resource_path("data/gameplay/catalog-v1.json").read_bytes()).hexdigest()


def available(kind, level=20, category=None):
    return [
        r
        for r in load().values()
        if r["kind"] == kind
        and r.get("level", 1) <= level
        and (category is None or r["category"] == category)
    ]
