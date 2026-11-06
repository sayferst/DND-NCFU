"""A source package creates finite units; trade rounds only the whole payment."""

import re

VERSION = "library-pack-1"


def register(spec):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "quantity": {"type": "integer", "minimum": 2, "maximum": 1000},
            "unit_name": {"type": "string", "minLength": 1, "maxLength": 80},
            "pack_price_cp": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "pack_mass_g": {"type": "integer", "minimum": 1, "maximum": 1000000000},
            "price_is_homebrew": {"type": "boolean"},
            "mass_is_homebrew": {"type": "boolean"},
        },
        "required": ["version", "quantity", "unit_name", "pack_price_cp", "pack_mass_g"],
    }
    spec["equipment_pack_v1"] = schema
    spec["source_equipment"]["properties"]["pack_v1"] = schema


def validate(program):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as validate_schema

    validate_schema(program, schemas()["equipment_pack_v1"])


def enrich(record, original_rules):
    name = record["attributes"]["source_name"]
    match = re.fullmatch(r"(.+?)\s*\((\d+)\s*(?:шт\.?|штук)?\)", name)
    if not match or not 2 <= int(match[2]) <= 1000 or original_rules["price_cp"] <= 0:
        return
    plurals = {
        "пули": "Пуля",
        "стрелы": "Стрела",
        "болты": "Болт",
        "иглы": "Игла",
        "патроны": "Патрон",
        "шипы, железные": "Шип, железный",
    }
    unit = plurals.get(match[1].casefold().strip(), "Единица: " + match[1])
    record["attributes"]["pack_v1"] = {
        "version": VERSION,
        "quantity": int(match[2]),
        "unit_name": unit[:80],
        "pack_price_cp": original_rules["price_cp"],
        "pack_mass_g": original_rules["mass_g"],
        "price_is_homebrew": "price_cp" in original_rules["homebrew_fields"],
        "mass_is_homebrew": "mass_g" in original_rules["homebrew_fields"],
    }


def normalize_rules(rules, program):
    validate(program)
    q = program["quantity"]
    rules["price_cp"] = (program["pack_price_cp"] + q - 1) // q
    rules["mass_g"] = (program["pack_mass_g"] + q - 1) // q
    if program["pack_price_cp"] % q:
        rules["homebrew_fields"].append("display_unit_price_rounding")
    if program["pack_mass_g"] % q:
        rules["homebrew_fields"].append("unit_mass_rounding")


def quote(engine, definition, quantity, percent, *, selling=False):
    program = definition.properties.get("library_pack_rules")
    if not program:
        return None
    validate(program)
    if engine.state.get("catalog_revision") != 3:
        raise ValueError("Package pricing requires canonical catalog3")
    if type(quantity) is not int or not 1 <= quantity <= 1000:
        raise ValueError("Invalid package unit quantity")
    if type(percent) is not int or not 1 <= percent <= 1000 or type(selling) is not bool:
        raise ValueError("Invalid market percentage or operation")
    numerator = program["pack_price_cp"] * quantity * percent
    denominator = program["quantity"] * (200 if selling else 100)
    price = numerator // denominator if selling else (numerator + denominator - 1) // denominator
    if price == 0:
        raise ValueError("Для продажи нужна партия стоимостью хотя бы один медный")
    return price
