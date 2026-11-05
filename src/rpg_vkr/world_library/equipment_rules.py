"""Explicit homebrew physical defaults around parsed source price, mass and dice."""

import re
from decimal import ROUND_HALF_UP, Decimal

VERSION = "library-equipment-1"


def compile_equipment(record):
    attributes = record["attributes"]
    facts = {r["field"]: r["value"] for r in attributes["facts"]}
    name = attributes["source_name"].casefold()
    kind = facts.get("type", "").casefold()
    invented = ["durability", "quality", "penetration"]
    price = facts.get("price", facts.get("cost", ""))
    match = re.fullmatch(
        r"\s*([0-9\s]+(?:[.,][0-9]+)?)\s*(мм|см|эм|зм|пм|cp|sp|ep|gp|pp)\.?\s*", price
    )
    if match:
        units = {
            "мм": 1,
            "см": 10,
            "эм": 50,
            "зм": 100,
            "пм": 1000,
            "cp": 1,
            "sp": 10,
            "ep": 50,
            "gp": 100,
            "pp": 1000,
        }
        number = Decimal(re.sub(r"\s", "", match[1]).replace(",", "."))
        price_cp = int((number * units[match[2]]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        price_cp = 10
        invented.append("price_cp")
    weight = facts.get("weight", "")
    match = re.fullmatch(r"\s*([0-9\s]+(?:[.,][0-9]+)?)\s*фнт\.?\s*", weight)
    if match:
        mass = int(
            (
                Decimal(re.sub(r"\s", "", match[1]).replace(",", ".")) * Decimal("453.59237")
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    else:
        mass = 500
        invented.append("mass_g")
    row = {
        "kind": "household",
        "category": "miscellaneous",
        "level": 1,
        "price_cp": price_cp,
        "mass_g": mass,
        "durability": 40,
        "quality": 1,
        "penetration": 0,
        "hands": 1,
        "stamina": 2,
        "dice": "1d4",
        "defence": 0,
        "dex_cap": 0,
        "required_ammunition": "",
        "ammo_kind": "",
        "rules_version": VERSION,
        "homebrew_fields": invented,
    }
    damage = re.search(r"\b([1-9][0-9]?)\s*[кd](4|6|8|10|12)\b", facts.get("damage", ""))
    if damage:
        row.update(kind="weapon", category="sword", dice=damage[1] + "d" + damage[2])
        properties = facts.get("properties", "").casefold()
        row["hands"] = 2 if "двуруч" in properties else 1
        if "кинжал" in name:
            row["category"] = "dagger"
        if "лук" in name:
            row.update(category="longbow", required_ammunition="arrow")
        if "арбалет" in name:
            row.update(category="crossbow", required_ammunition="bolt")
        if any(word in kind for word in ("огнестрел", "порох")):
            row.update(category="crossbow", required_ammunition="bullet")
    elif "доспех" in kind or "щит" in name:
        ac = facts.get("ac", facts.get("armor_class", ""))
        number = re.search(r"\d+", ac)
        row.update(
            kind="armour",
            category="shield" if "щит" in name else "body",
            defence=int(number[0]) if number else 2 if "щит" in name else 10,
            dex_cap=2 if "макс" in ac.casefold() else 10 if "ловк" in ac.casefold() else 0,
        )
        if not number and "щит" not in name:
            invented.append("defence")
    elif any(word in name for word in ("стрелы", "болты", "пули")):
        row.update(
            category="ammunition",
            ammo_kind="arrow" if "стрелы" in name else "bolt" if "болты" in name else "bullet",
        )
    validate_equipment(row)
    return row


def validate_equipment(row):
    keys = {
        "kind",
        "category",
        "level",
        "price_cp",
        "mass_g",
        "durability",
        "quality",
        "penetration",
        "hands",
        "stamina",
        "dice",
        "defence",
        "dex_cap",
        "required_ammunition",
        "ammo_kind",
        "rules_version",
        "homebrew_fields",
    }
    if not isinstance(row, dict) or set(row) != keys:
        raise ValueError("Unknown equipment fields")
    if row.get("rules_version") != VERSION or row.get("kind") not in {
        "weapon",
        "armour",
        "household",
    }:
        raise ValueError("Unknown library equipment rules")
    for key, maximum in (
        ("price_cp", 1000000000),
        ("mass_g", 1000000000),
        ("durability", 1000),
        ("defence", 30),
        ("dex_cap", 10),
        ("hands", 2),
        ("stamina", 10),
    ):
        if type(row.get(key)) is not int or not 0 <= row[key] <= maximum:
            raise ValueError("Invalid equipment value: " + key)
    if not re.fullmatch(r"[1-9][0-9]?d(?:4|6|8|10|12)", row.get("dice", "")):
        raise ValueError("Invalid equipment damage dice")
    if row.get("required_ammunition") not in {"", "arrow", "bolt", "bullet"}:
        raise ValueError("Unknown ammunition requirement")
    if row.get("ammo_kind") not in {"", "arrow", "bolt", "bullet"}:
        raise ValueError("Unknown ammunition kind")
    if row.get("category") not in {
        "miscellaneous",
        "sword",
        "dagger",
        "longbow",
        "crossbow",
        "body",
        "shield",
        "ammunition",
    }:
        raise ValueError("Unknown equipment category")
    if not row["hands"] or not row["stamina"] or not row["durability"]:
        raise ValueError("Equipment needs nonzero costs and durability")
    if row["level"] != 1 or row["quality"] != 1 or row["penetration"] != 0:
        raise ValueError("Unsupported equipment balance modifiers")
    if not isinstance(row["homebrew_fields"], list) or not set(row["homebrew_fields"]) <= {
        "durability",
        "quality",
        "penetration",
        "price_cp",
        "mass_g",
        "defence",
    }:
        raise ValueError("Unknown homebrew field")
