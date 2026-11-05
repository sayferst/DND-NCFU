"""Additional source programs, separately versioned from the frozen v3 actions."""

import re

from rpg_vkr.world_library.creature_actions import text

VERSION = "library-resilience-1"


def register(spec):
    schema = {
        "type": "object",
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "undead_fortitude": {"type": "boolean"},
            "supported_names": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "maxLength": 200},
            },
        },
        "required": ["version", "undead_fortitude", "supported_names"],
        "additionalProperties": False,
    }
    spec["source_resilience_v1"] = schema
    spec["source_creature"]["properties"]["resilience_v1"] = schema


def validate(program):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as validate_schema

    validate_schema(program, schemas()["source_resilience_v1"])
    if bool(program["supported_names"]) != program["undead_fortitude"]:
        raise ValueError("Source program names must match its executable operation")


def extract(stat):
    program = {"version": VERSION, "undead_fortitude": False, "supported_names": []}
    for row in stat.get("черты", []):
        if not isinstance(row, dict):
            continue
        name, body = text(row.get("название")), text(row.get("описание")).casefold()
        if name.casefold().rstrip(". ") != "стойкость нежити":
            continue
        # Only the standard complete rule. Variants remain pending for another program.
        requirements = (
            r"хит[^.;]{0,80}\b0\b",
            r"спасброс\w*\s+телосложения",
            r"5\s*\+\s*(?:полученн|причиненн|урон)",
            r"(?:излучени|лучист)",
            r"критическ",
            r"(?:при успехе|в случае успеха)[^.]*хит[^.]*\b1\.?\s*$",
        )
        if all(re.search(p, body) for p in requirements) and not any(
            word in body
            for word in (
                "перезаряд",
                "раз в день",
                "/день",
                "кислот",
                "огн",
                "вместо спас",
                "временны",
                "бонусным",
                "дополнительн",
            )
        ):
            program["undead_fortitude"] = True
            program["supported_names"].append(name[:200])
    return program


def incoming(engine, target, amount, *, radiant=False, critical=False, nonlethal=False):
    if target == "hero" or not amount or critical or radiant or nonlethal:
        return amount
    entity, definition = engine.actor(target, alive=False)
    program = definition.properties.get("library_resilience_rules")
    if not program:
        return amount
    validate(program)
    hp = engine.hp(target)
    if not program["undead_fortitude"] or hp <= 0 or amount < hp:
        return amount
    if (entity.state or {}).get("life") == "dead":
        return amount
    from rpg_vkr.world_library.source_runtime import saving_throw_extended

    dc = 5 + amount
    saved = saving_throw_extended(engine, target, "constitution", dc)
    engine.events.append(
        {
            "kind": "source_undead_fortitude",
            "version": VERSION,
            "actor": target,
            "damage": amount,
            "dc": dc,
            "saved": saved,
        }
    )
    return hp - 1 if saved else amount
