"""Original library objects mapped to bounded canonical equipment operations."""

from rpg_vkr.world_library.equipment_rules import compile_equipment, validate_equipment

VERSION = "library-equipment-2"
PROFILES = {
    "weapon",
    "armour",
    "ammunition",
    "tool",
    "material",
    "ore",
    "ingredient",
    "plant",
    "medicine",
    "poison",
    "food",
    "book",
    "quest",
}


def instance_rules(entity, definition):
    rules = (entity.state or {}).get("library_instance_rules")
    if rules is None:
        return None
    validate_physical(rules)
    if (
        definition.id not in {"mat_ash", "mat_oak", "mat_iron", "mat_copper"}
        or rules["source_profile"] != "material"
    ):
        raise ValueError("Instance material rules require an explicit legacy alias")
    return rules


def compile_physical(record):
    a, profile = record["attributes"], record["profile"]
    if profile not in PROFILES:
        raise ValueError("Unsupported physical profile")
    row = compile_equipment({"attributes": {"source_name": "", "facts": []}})
    row.update(
        rules_version=VERSION,
        source_profile=profile,
        capability="",
        strength=1,
        price_cp=record["price_cp"],
        mass_g=a["mass_g"],
        durability=a["durability"],
        quality=a["quality"],
        homebrew_fields=[],
    )
    if profile == "weapon":
        name = record["name"].casefold()
        row.update(
            kind="weapon",
            category="dagger" if "кинжал" in name else "sword",
            hands=a["hands"],
            dice=f"{a['damage_count']}d{a['damage_die']}",
            penetration=a["penetration"],
        )
        if "лук" in name:
            row.update(category="longbow", required_ammunition="arrow")
        if "арбалет" in name or "праща" in name:
            row.update(
                category="crossbow", required_ammunition="bolt" if "арбалет" in name else "bullet"
            )
    elif profile == "armour":
        row.update(
            kind="armour",
            category="shield" if a["slot"] == "shield" else "body",
            defence=a["defence"] if a["slot"] == "shield" else 10 + a["defence"],
            dex_cap=2,
        )
    elif profile == "ammunition":
        row.update(
            category="ammunition",
            ammo_kind={"лук": "arrow", "арбалет": "bolt", "праща": "bullet"}[a["compatible"]],
            penetration=a["penetration"],
        )
    elif profile == "tool":
        row.update(capability="tools", strength=1)
    validate_physical(row)
    return row


def validate_physical(row):
    if set(row) - {"source_profile", "capability", "strength"} != set(
        compile_equipment({"attributes": {"source_name": "", "facts": []}})
    ):
        raise ValueError("Unknown original physical fields")
    if row.get("source_profile") not in PROFILES or row.get("rules_version") != VERSION:
        raise ValueError("Unknown original physical rules")
    if row.get("capability") not in {"", "tools"} or row.get("strength") != 1:
        raise ValueError("Unknown physical capability")
    for field, low, high in (("quality", 1, 5), ("penetration", 0, 6)):
        if type(row.get(field)) is not int or not low <= row[field] <= high:
            raise ValueError("Physical quality/penetration outside bounds")
    # Reuse all immutable V1 field and enum bounds after removing V2 additions.
    base = {k: v for k, v in row.items() if k not in {"source_profile", "capability", "strength"}}
    base.update(rules_version="library-equipment-1", quality=1, penetration=0)
    validate_equipment(base)
