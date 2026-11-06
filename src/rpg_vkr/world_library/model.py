"""Strict, portable JSON Schema subset and cross-record content constraints."""

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode("utf-8")).hexdigest()


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate(value, schema, path="record"):
    """Only the keywords emitted by schemas.json; unknown keywords fail closed."""
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "maxItems",
        "minItems",
        "$schema",
        "title",
    }
    if set(schema) - allowed:
        raise ValueError("Unsupported schema keyword")
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind and type(value) is not types[kind]:
        raise ValueError(path + ": expected " + kind)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + ": enum")
    if kind == "object":
        props = schema.get("properties", {})
        if not set(schema.get("required", [])) <= value.keys():
            raise ValueError(path + ": required fields")
        if schema.get("additionalProperties") is False and set(value) - props.keys():
            raise ValueError(path + ": unknown fields")
        for key, child in value.items():
            if key in props:
                validate(child, props[key], path + "." + key)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ValueError(path + ": array length")
        for child in value:
            validate(child, schema["items"], path + "[]")
    elif kind == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4000):
            raise ValueError(path + ": text length")
        if any(ord(c) < 32 for c in value):
            raise ValueError(path + ": control characters")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(path + ": pattern")
    elif kind == "integer":
        if not schema.get("minimum", -(10**9)) <= value <= schema.get("maximum", 10**9):
            raise ValueError(path + ": range")


@lru_cache(maxsize=1)
def schemas():
    return json.loads((ROOT / "data/world_library/schemas.json").read_text(encoding="utf-8"))


def validate_record(record):
    spec = schemas()
    validate(record, spec["record"])
    validate(record["attributes"], spec[record["profile"]], "attributes")
    if record["category"].split(".")[-1] != record["profile"]:
        raise ValueError("Category/profile mismatch")
    a = record["attributes"]
    if record["profile"] == "npc" and "social_version" in a:
        from rpg_vkr.world_library.social_rules import compile_social

        if not {"abilities", "armour_class", "damage_dice"} <= a.keys():
            raise ValueError("Versioned NPC needs a complete stat block")
        compile_social(record)
    if (
        record["profile"] in {"food", "medicine", "poison", "book", "quest"}
        and "utility_version" in a
    ):
        from rpg_vkr.world_library.utility_rules import compile_utility

        compile_utility(record)
    if record["profile"] == "source_reference":
        from rpg_vkr.world_library.reference_details import validate_details

        validate_details(a, spec, validate)
        if a.get("mechanics_state") == "mp-adapted" and "source_spell_v1" not in a:
            raise ValueError("MP-adapted reference requires a source spell program")
        if "source_spell_v1" in a:
            from rpg_vkr.world_library.source_magic_rules import validate as validate_source_spell

            validate_source_spell(a["source_spell_v1"])
            if a.get("mechanics_state") != "mp-adapted":
                raise ValueError("Source spell must declare MP adaptation")
            if (
                a["record_type"] != "spell"
                or a["details"]["level"] != a["source_spell_v1"]["level"]
            ):
                raise ValueError("Source spell program must match its typed spell level")
    if record["profile"] == "source_creature" and "actions_v2" in a:
        from rpg_vkr.world_library.creature_actions import validate as validate_actions

        validate_actions(a["actions_v2"])
    if record["profile"] == "source_creature" and "features_v3" in a:
        from rpg_vkr.world_library.source_extract import validate as validate_source

        validate_source(a["features_v3"], a["actions_v2"])
    if record["profile"] == "source_creature" and "resilience_v1" in a:
        from rpg_vkr.world_library.resilience_rules import validate as validate_resilience

        validate_resilience(a["resilience_v1"])
    if record["profile"] == "source_creature" and "multiattack_v1" in a:
        from rpg_vkr.world_library.multiattack_rules import validate as validate_multiattack

        validate_multiattack(a["multiattack_v1"], a["actions_v2"]["actions"], a["features_v3"])
    if record["profile"] == "source_creature" and "regeneration_v1" in a:
        from rpg_vkr.world_library.regeneration_rules import validate as validate_regeneration

        validate_regeneration(a["regeneration_v1"])
    if record["profile"] == "source_equipment" and "pack_v1" in a:
        from rpg_vkr.world_library.equipment_packs import validate as validate_pack

        validate_pack(a["pack_v1"])
        pack = a["pack_v1"]
        if record["price_cp"] != (pack["pack_price_cp"] + pack["quantity"] - 1) // pack["quantity"]:
            raise ValueError("Package display unit price must match its declared quantity")
    if record["profile"] in {"npc", "creature", "boss"}:
        if a["hp_max"] > 20 + 40 * a["level"]:
            raise ValueError("Actor exceeds homebrew HP envelope")
    if record["profile"] == "weapon" and a["damage_die"] * a["damage_count"] > 24:
        raise ValueError("Weapon exceeds mundane damage envelope")
    if record["profile"] == "spell" and a["mp"] < a["level"]:
        raise ValueError("Spell MP below level")
    if record["profile"] == "spell" and "rules" in a:
        from rpg_vkr.world_library.magic_rules import compile_magic

        compile_magic(record, [])
    return record


def validate_bundle(records):
    by_id = {}
    names = set()
    for row in records:
        validate_record(row)
        key = (row["profile"], normalized(row["name"]))
        if row["id"] in by_id or key in names:
            raise ValueError("Duplicate ID or normalized name")
        by_id[row["id"]] = row
        names.add(key)
    for row in records:
        if row["profile"] == "npc" and "social_version" in row["attributes"]:
            species = row["attributes"]["species"]
            target = by_id.get(species)
            if target is None or not (
                target["profile"] == "race"
                or (
                    target["profile"] == "source_reference"
                    and target["attributes"].get("record_type") == "race"
                )
            ):
                raise ValueError("Authored NPC requires a known species/race template")
            species_links = [link for link in row["links"] if link["relation"] == "species"]
            if (
                len(species_links) != 1
                or species_links[0]["target"] != species
                or species_links[0]["quantity"] != 1
            ):
                raise ValueError("NPC species must match its pinned species link")
            for link in row["links"]:
                if link["relation"] == "starting_inventory" and by_id.get(link["target"], {}).get(
                    "profile"
                ) in {
                    "npc",
                    "creature",
                    "boss",
                    "source_creature",
                    "race",
                    "skill",
                    "source_reference",
                }:
                    raise ValueError(
                        "NPC starting inventory requires physical/spell/recipe templates"
                    )
        if row["profile"] == "source_reference" and row["attributes"].get("record_type") in {
            "class",
            "race",
        }:
            details = row["attributes"]["details"]
            parent = details["parent_global_id"]
            children = details["child_ids"]
            if len(set(children)) != len(children) or row["id"] in children or parent == row["id"]:
                raise ValueError("Duplicate/self hierarchy reference")
            for target in ([parent] if parent else []) + children:
                if (
                    target not in by_id
                    or by_id[target]["attributes"].get("record_type")
                    != row["attributes"]["record_type"]
                ):
                    raise ValueError("Missing/incompatible hierarchy reference")
            if parent and row["id"] not in by_id[parent]["attributes"]["details"]["child_ids"]:
                raise ValueError("Nonreciprocal hierarchy parent")
            if any(
                by_id[child]["attributes"]["details"]["parent_global_id"] != row["id"]
                for child in children
            ):
                raise ValueError("Nonreciprocal hierarchy child")
            trail = {row["id"]}
            ancestor = parent
            while ancestor:
                if ancestor in trail or len(trail) > 8:
                    raise ValueError("Hierarchy cycle/depth")
                trail.add(ancestor)
                ancestor = by_id[ancestor]["attributes"]["details"]["parent_global_id"]
        for link in row["links"]:
            if link["target"] not in by_id or link["target"] == row["id"]:
                raise ValueError("Missing/self reference: " + link["target"])
            if link["relation"] == "component" and by_id[link["target"]]["profile"] not in {
                "material",
                "ore",
                "ingredient",
                "plant",
            }:
                raise ValueError("Invalid component profile")
            if (
                link["relation"] in {"spell", "combines"}
                and by_id[link["target"]]["profile"] != "spell"
            ):
                raise ValueError("Magic carrier/combination must reference a spell")
        if row["profile"] == "recipe":
            if not {"input", "output"} <= {x["relation"] for x in row["links"]}:
                raise ValueError("Recipe needs inputs and outputs")
            ins = sum(
                by_id[x["target"]]["price_cp"] * x["quantity"]
                for x in row["links"]
                if x["relation"] == "input"
            )
            outs = sum(
                by_id[x["target"]]["price_cp"] * x["quantity"]
                for x in row["links"]
                if x["relation"] == "output"
            )
            if outs > ins + row["attributes"]["labour_cp"]:
                raise ValueError("Recipe creates unbudgeted value")
    complete = set()

    def visit(key, trail):
        if key in trail or len(trail) > 32:
            raise ValueError("Composition cycle/depth")
        if key in complete:
            return
        for link in by_id[key]["links"]:
            if link["relation"] == "component":
                visit(link["target"], trail | {key})
        complete.add(key)

    for key in by_id:
        visit(key, set())
    return by_id


def read_jsonl(path, *, dependencies=()):
    result = []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if len(line) > 64000 or len(result) >= 100000:
                raise ValueError("Import limit")
            if line.strip():
                result.append(json.loads(line))
    validate_bundle([*dependencies, *result])
    return result


def equipment_records():
    """Validate the equipment shard against its explicit canonical material shard."""
    seed = read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")
    return read_jsonl(ROOT / "data/world_library/rpgd100-equipment-facts.jsonl", dependencies=seed)


def all_records():
    """One manifest order for CLI, window, tests and export tooling."""
    records = []
    for name in (
        "seed-v1.jsonl",
        "rpgd100-creature-facts.jsonl",
        "rpgd100-equipment-facts.jsonl",
        "rpgd100-reference-index.jsonl",
    ):
        path = ROOT / "data/world_library" / name
        if path.exists():
            records.extend(
                read_jsonl(
                    path, dependencies=records if name == "rpgd100-equipment-facts.jsonl" else ()
                )
            )
    validate_bundle(records)
    return records
