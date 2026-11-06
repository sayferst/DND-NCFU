"""Finite source regeneration; explicit death timing never resurrects an already dead actor."""

import re
from dataclasses import replace

from rpg_vkr.world_library.creature_actions import text

VERSION = "library-regeneration-1"
ELEMENT_WORDS = {
    "кислот": "acid",
    "огн": "fire",
    "холод": "cold",
    "электр": "lightning",
    "излучен": "radiant",
    "некрот": "necrotic",
    "яд": "poison",
    "псих": "psychic",
    "звуком": "thunder",
    "силовым полем": "force",
}


def register(spec):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "amount": {"type": "integer", "minimum": 1, "maximum": 100},
            "minimum_hp": {"type": "integer", "enum": [0, 1]},
            "suppress_elements": {
                "type": "array",
                "maxItems": 10,
                "items": {"type": "string", "enum": sorted(ELEMENT_WORDS.values())},
            },
            "zero_death": {"type": "boolean"},
            "supported_names": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {"type": "string", "maxLength": 200},
            },
        },
        "required": [
            "version",
            "amount",
            "minimum_hp",
            "suppress_elements",
            "zero_death",
            "supported_names",
        ],
    }
    spec["source_regeneration_v1"] = schema
    spec["source_creature"]["properties"]["regeneration_v1"] = schema


def validate(program):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as validate_schema

    validate_schema(program, schemas()["source_regeneration_v1"])
    if len(set(program["suppress_elements"])) != len(program["suppress_elements"]):
        raise ValueError("Duplicate regeneration suppression element")
    if program["zero_death"] and program["minimum_hp"]:
        raise ValueError("Zero-HP regeneration must be executable at zero HP")


def extract(stat):
    for row in stat.get("черты", []):
        if not isinstance(row, dict):
            continue
        name = text(row.get("название"))
        if name.casefold().rstrip(". ") != "регенерация":
            continue
        body = text(row.get("описание")).casefold().replace("ё", "е").strip(" .")
        clauses = body.split(". ")
        # Every sentence must match; no environmental, form, tether or material assumptions.
        first = re.fullmatch(
            r"[а-яa-z -]{1,100} восстанавливает (?:по )?(\d+) хит(?:а|ов)? "
            r"в начале (?:каждого )?своего хода"
            r"(?:, если у [а-яa-z -]{1,100} (?:есть|остался|остается) хотя бы 1 хит)?",
            clauses[0],
        )
        if not first or not 1 <= int(first[1]) <= 100:
            continue
        program = {
            "version": VERSION,
            "amount": int(first[1]),
            "minimum_hp": int("хотя бы" in clauses[0]),
            "suppress_elements": [],
            "zero_death": False,
            "supported_names": [name[:200]],
        }
        valid = True
        for clause in clauses[1:]:
            suppression = re.fullmatch(
                r"если [а-яa-z -]{1,100} получает (.{1,120}), "
                r"(?:то )?эта (?:особенность|способность) не (?:действует|работает) "
                r"в начале (?:его |ее |их )?следующего хода(?: [а-яa-z -]{1,100})?",
                clause,
            )
            if suppression and not program["suppress_elements"]:
                phrase = suppression[1]
                elements = [value for stem, value in ELEMENT_WORDS.items() if stem in phrase]
                remainder = phrase
                for stem in ELEMENT_WORDS:
                    remainder = re.sub(stem + r"[а-я]*", "", remainder)
                remainder = re.sub(r"\b(?:урон|или|и|а|также|энергией)\b|[,\s]", "", remainder)
                if elements and not remainder:
                    program["suppress_elements"] = sorted(set(elements))
                    continue
            if not program["zero_death"] and re.fullmatch(
                r"[а-яa-z -]{1,100} умирает(?:,)? только (?:в том случае, )?если "
                r"(?:он |она |оно |они )?начинает (?:свой )?ход с 0 хит(?:ов|ами)? "
                r"и не (?:может регенерировать|регенерирует)",
                clause,
            ):
                program["zero_death"] = True
                continue
            valid = False
            break
        if valid and not (program["zero_death"] and program["minimum_hp"]):
            return program
    return None


def program(engine, actor):
    if actor == "hero":
        return None
    entity = engine.actors.get(actor)
    if entity is None:
        return None
    definition = engine.definitions[entity.definition_id]
    if definition.kind != "actor":
        return None
    value = definition.properties.get("library_regeneration_rules")
    if value is not None:
        validate(value)
    return value


def state(engine, actor):
    entity = engine.actors[actor]
    value = (entity.state or {}).get("library_regeneration", {"version": 1, "suppressed": False})
    if (
        type(value) is not dict
        or set(value) != {"version", "suppressed"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["suppressed"]) is not bool
    ):
        raise ValueError("Invalid saved regeneration state")
    return dict(value)


def save_state(engine, actor, value):
    entity = engine.actors[actor]
    engine.actors[actor] = replace(
        entity, state=dict(entity.state or {}, library_regeneration=value)
    )


def record_damage(engine, actor, components):
    spec = program(engine, actor)
    if spec is None:
        return
    if any(amount > 0 and element in spec["suppress_elements"] for amount, element in components):
        current = state(engine, actor)
        current["suppressed"] = True
        save_state(engine, actor, current)
        engine.events.append(
            {"kind": "source_regeneration_suppressed", "actor": actor, "version": VERSION}
        )


def defer_damage_death(engine, actor, before, after):
    """Source-specific death timing; native Life math remains unchanged for every other actor."""
    spec = program(engine, actor)
    if (
        spec is None
        or not spec["zero_death"]
        or before.dead
        or not after.dead
        or before.exhaustion == 6
    ):
        return after
    engine.events.append(
        {"kind": "source_regeneration_death_deferred", "actor": actor, "version": VERSION}
    )
    return replace(after, dead=False, stable=False, successes=0, failures=0)


def dead(engine, actor):
    if (engine.actors[actor].state or {}).get("life") == "dead":
        return True
    if engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import life

        return life(engine, actor).dead
    return False


def pending_zero(engine, actor):
    spec = program(engine, actor)
    return bool(
        spec and spec["minimum_hp"] == 0 and engine.hp(actor) == 0 and not dead(engine, actor)
    )


def start_turn(engine, actor):
    spec = program(engine, actor)
    if spec is None or dead(engine, actor):
        return
    current = state(engine, actor)
    suppressed = current["suppressed"]
    current["suppressed"] = False
    save_state(engine, actor, current)
    hp = engine.hp(actor)
    if hp == 0 and spec["zero_death"] and suppressed:
        if engine.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules_runtime import apply, life

            apply(
                engine,
                actor,
                replace(
                    life(engine, actor),
                    dead=True,
                    stable=False,
                    successes=0,
                    failures=0,
                    knocked_out=False,
                ),
            )
        else:
            entity = engine.actors[actor]
            engine.actors[actor] = replace(
                entity, state=dict(entity.state or {}, hp=0, life="dead")
            )
        engine.events.append(
            {"kind": "source_regeneration_death", "actor": actor, "version": VERSION}
        )
        return
    healed = 0
    if not suppressed and hp >= spec["minimum_hp"]:
        engine.change_hp(actor, spec["amount"])
        healed = engine.hp(actor) - hp
    engine.events.append(
        {
            "kind": "source_regeneration_turn",
            "actor": actor,
            "version": VERSION,
            "suppressed": suppressed,
            "healed": healed,
        }
    )


def advance(engine, start, end):
    if engine.state.get("battle") or end <= start:
        return
    turns = (end - start) * 10
    for actor in list(engine.actors):
        spec = program(engine, actor)
        if spec is None or dead(engine, actor):
            continue
        maximum = engine.definitions[engine.actors[actor].definition_id].properties["hp_max"]
        if engine.hp(actor) == maximum and not state(engine, actor)["suppressed"]:
            continue
        start_turn(engine, actor)
        if (
            turns > 1
            and not dead(engine, actor)
            and spec["minimum_hp"] <= engine.hp(actor) < maximum
        ):
            before = engine.hp(actor)
            engine.change_hp(actor, min(1000000, spec["amount"] * (turns - 1)))
            engine.events.append(
                {
                    "kind": "source_regeneration_elapsed",
                    "actor": actor,
                    "turns": turns - 1,
                    "healed": engine.hp(actor) - before,
                    "version": VERSION,
                }
            )
