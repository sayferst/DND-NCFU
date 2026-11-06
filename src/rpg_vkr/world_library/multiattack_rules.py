"""Closed source multiattack choices and hit-triggered follow-up attacks."""

import re
from copy import deepcopy

VERSION = "library-multiattack-1"


def register(spec):
    integer = {"type": "integer", "minimum": 0, "maximum": 29}
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "choices": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {"type": "array", "minItems": 1, "maxItems": 8, "items": integer},
            },
            "followups": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"after": integer, "attack": integer},
                    "required": ["after", "attack"],
                },
            },
        },
        "required": ["version", "choices", "followups"],
    }
    spec["source_multiattack_v1"] = schema
    spec["source_creature"]["properties"]["multiattack_v1"] = deepcopy(schema)


def validate(program, actions, features=None):
    actions = deepcopy(actions)
    for rider in (features or {}).get("riders", []):
        actions[rider["index"]]["complete"] = True
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as schema_validate

    schema_validate(program, schemas()["source_multiattack_v1"])
    for sequence in program["choices"]:
        for index in sequence:
            if index >= len(actions) or not actions[index]["complete"]:
                raise ValueError("Multiattack requires complete referenced attacks")
    if any(
        len(s) + sum(i == r["after"] for i in s for r in program["followups"]) > 8
        for s in program["choices"]
    ):
        raise ValueError("Multiattack exceeds eight finite attacks")
    if len({tuple(s) for s in program["choices"]}) != len(program["choices"]):
        raise ValueError("Duplicate multiattack choices")
    for trigger in program["followups"]:
        if trigger["after"] not in {i for s in program["choices"] for i in s}:
            raise ValueError("Follow-up trigger outside base sequence")
        index = trigger["attack"]
        if index >= len(actions) or not actions[index]["complete"]:
            raise ValueError("Incomplete follow-up attack")
    if len(program["followups"]) != len({(r["after"], r["attack"]) for r in program["followups"]}):
        raise ValueError("Duplicate follow-up trigger")


def extract(stat, attacks, features):
    from rpg_vkr.world_library.creature_actions import text
    from rpg_vkr.world_library.source_extract import action_matches, source_sequence

    actions = deepcopy(attacks["actions"])
    for rider in features["riders"]:
        actions[rider["index"]]["complete"] = True
    body = next(
        (
            text(r.get("описание")).casefold()
            for r in stat.get("действия", [])
            if isinstance(r, dict)
            and text(r.get("название")).casefold().strip(". ") == "мультиатака"
        ),
        "",
    )
    # Require the entire conditional clause and the same target; no partial prose execution.
    match = re.fullmatch(
        r"(.+?\.) если [а-яёa-z -]{1,100} попадает ([а-яё -]+), "
        r"он может совершить одну атаку ([а-яё -]+) по той же самой цели\.?",
        body,
    )
    if match:
        base = source_sequence(match[1], actions)
        before = [i for i, a in enumerate(actions) if action_matches(a["name"], match[2])]
        after = [i for i, a in enumerate(actions) if action_matches(a["name"], match[3])]
        if (
            base
            and len(before) == len(after) == 1
            and before[0] in base
            and actions[after[0]]["complete"]
        ):
            return {
                "version": VERSION,
                "choices": [base],
                "followups": [{"after": before[0], "attack": after[0]}],
            }
    # Two same-type attacks, or one of each. A duplicated word in a source
    # sentence is accepted only in this otherwise fully matched construction.
    mixed = re.fullmatch(
        r"[а-яёa-z -]{1,100} совершает или две атаки ([а-яё -]+), "
        r"или две атаки ([а-яё -]+), или по одной каждой (?:каждой )?из них\.?",
        body,
    )
    if mixed:
        found = [
            [i for i, a in enumerate(actions) if action_matches(a["name"], phrase)]
            for phrase in (mixed[1], mixed[2])
        ]
        if all(len(indices) == 1 for indices in found):
            first, second = found[0][0], found[1][0]
            if first != second and actions[first]["complete"] and actions[second]["complete"]:
                return {
                    "version": VERSION,
                    "choices": [[first, first], [second, second], [first, second]],
                    "followups": [],
                }
    # Exactly one of the explicitly named alternative repeated attacks.
    match = re.fullmatch(
        r"([а-яёa-z -]{1,100} совершает (?:две|три|четыре|[1-8]) атаки) "
        r"([а-яё -]+) или ([а-яё -]+)\.?",
        body,
    )
    if match:
        choices = [source_sequence(match[1] + " " + part, actions) for part in (match[2], match[3])]
        if all(choices) and choices[0] != choices[1]:
            return {"version": VERSION, "choices": choices, "followups": []}
    return None


def choose(engine, actor, target, program, select):
    from rpg_vkr.world_library.source_geometry import distance

    separation = distance(engine, actor, target)
    # Deterministic preference for the sequence with most currently reachable attacks.
    return max(
        program["choices"], key=lambda s: sum(separation <= select(i)["maximum_range"] for i in s)
    )
