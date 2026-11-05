"""Versioned source attack choices and exact, bounded multiattack sequences."""

import re

VERSION = "library-creature-2"
ELEMENTS = {
    "дробящ": "physical",
    "колющ": "physical",
    "рубящ": "physical",
    "огн": "fire",
    "холод": "cold",
    "электр": "lightning",
    "кислот": "acid",
    "яд": "poison",
    "некрот": "necrotic",
    "излуч": "radiant",
    "псих": "psychic",
    "звук": "thunder",
    "силов": "force",
}
DICE = r"[1-9][0-9]?d(?:4|6|8|10|12)(?:[+-][0-9]{1,2})?"


def text(value):
    from html import unescape

    return " ".join(unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def register(spec):
    from copy import deepcopy

    def integer(lo, hi):
        return {"type": "integer", "minimum": lo, "maximum": hi}

    action = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 200},
            "bonus": integer(-10, 40),
            "dice": {"type": "string", "pattern": DICE, "maxLength": 40},
            "element": {"type": "string", "enum": sorted(set(ELEMENTS.values()))},
            "ranged": {"type": "boolean"},
            "complete": {"type": "boolean"},
        },
        "additionalProperties": False,
    }
    action["required"] = list(action["properties"])
    action["properties"]["components"] = {
        "type": "array",
        "maxItems": 4,
        "items": {
            "type": "object",
            "properties": {
                "dice": {"type": "string", "pattern": DICE, "maxLength": 40},
                "element": {"type": "string", "enum": sorted(set(ELEMENTS.values()))},
            },
            "required": ["dice", "element"],
            "additionalProperties": False,
        },
    }
    schema = {
        "type": "object",
        "properties": {
            "actions": {"type": "array", "items": action, "maxItems": 30},
            "multiattack": {"type": "array", "items": integer(0, 29), "maxItems": 8},
            "multiattack_complete": {"type": "boolean"},
        },
        "required": ["actions", "multiattack", "multiattack_complete"],
        "additionalProperties": False,
    }
    for field in ("force_resistance", "force_immunity", "force_vulnerability"):
        schema["properties"][field] = {"type": "boolean"}
    spec["creature_actions_v2"] = schema
    spec["source_creature"]["properties"]["actions_v2"] = deepcopy(schema)


def extract(stat):
    actions, multi = [], ""
    for row in stat.get("действия", []):
        if not isinstance(row, dict):
            continue
        name, body = text(row.get("название"))[:200], text(row.get("описание"))
        if name.casefold().strip(".") == "мультиатака":
            multi = body.casefold()
            continue
        bonus = re.search(r"([+-]\s*\d+)\s*к\s*попаданию", body, re.I)
        hit = re.search(r"Попадание\s*:\s*(.*)", body, re.I)
        if not bonus or not hit:
            continue
        damage = re.findall(r"\b([1-9][0-9]?)\s*[кd](4|6|8|10|12)(\s*[+-]\s*\d{1,2})?", hit[1])
        if not damage or len(actions) == 30:
            continue
        formula = damage[0][0] + "d" + damage[0][1] + re.sub(r"\s", "", damage[0][2])
        value = int(bonus[1].replace(" ", ""))
        if not -10 <= value <= 40:
            continue
        lower = hit[1].casefold()
        element = next((element for stem, element in ELEMENTS.items() if stem in lower), "")
        # Strictly one unconditional damage sentence. Additional text stays unsupported.
        components, complete = damage_components(lower)
        actions.append(
            {
                "name": name,
                "bonus": value,
                "dice": formula,
                "element": components[0]["element"] if complete else element or "physical",
                "ranged": "дальнобойная" in body.casefold(),
                "complete": complete,
                "components": components,
            }
        )
    sequence = parse_multiattack(multi, actions)
    result = {"actions": actions, "multiattack": sequence, "multiattack_complete": bool(sequence)}
    for source, field in (
        ("сопротивления", "force_resistance"),
        ("иммунитеты", "force_immunity"),
        ("уязвимости", "force_vulnerability"),
    ):
        values = stat.get(source, [])
        if isinstance(values, dict):
            values = values.get("урон", [])
        if isinstance(values, str):
            values = re.split("[,;]", values)
        result[field] = isinstance(values, list) and any(
            isinstance(v, str)
            and v.strip().casefold() in {"силовое поле", "силовому полю", "силовым полем"}
            for v in values
        )
    return result


def damage_components(value):
    formula = r"([1-9][0-9]?)\s*[кd](4|6|8|10|12)(\s*[+-]\s*\d{1,2})?"
    kinds = (
        r"(?:дробящего|колющего|рубящего|некротического|психического)\s+урона"
        r"|урона\s+(?:огн[её]м|холодом|электричеством|кислотой|ядом|"
        r"некротической\s+энергией|излучением|психической\s+энергией|силовым\s+полем|звуком)"
    )
    pattern = re.compile(r"\d+\s*\(" + formula + r"\)\s+(" + kinds + r")")
    parts = []
    for match in pattern.finditer(value):
        element = next((element for stem, element in ELEMENTS.items() if stem in match[4]), "")
        if not element or len(parts) == 4:
            return parts, False
        dice = match[1] + "d" + match[2] + re.sub(r"\s", "", match[3] or "")
        parts.append({"dice": dice, "element": element})
    remainder = pattern.sub("#", value).strip(" .")
    complete = bool(parts and re.fullmatch(r"#(?:\s*(?:,|плюс|и|а также)\s*#)*", remainder))
    return parts, complete


def parse_multiattack(body, actions):
    """Only explicit sequences of named attacks; no substitutions/conditions inferred."""
    if not body or any(word in body for word in ("или", "если", "может", "заклин", "вместо")):
        return []
    counts = {
        "одну": 1,
        "одна": 1,
        "один": 1,
        "одним": 1,
        "два": 2,
        "две": 2,
        "двумя": 2,
        "три": 3,
        "тремя": 3,
        "четыре": 4,
        "четырьмя": 4,
        "пять": 5,
        "шесть": 6,
    }
    total = re.search(r"совершает\s+(одну|две|три|четыре|пять|шесть|\d+)\s+атак", body)
    if not total:
        return []
    expected = counts.get(total[1], int(total[1]) if total[1].isdigit() else 0)
    if not 1 <= expected <= 8:
        return []

    # Match grammatical stems only when they identify exactly one source action.
    def identify(fragment):
        tokens = re.findall(r"[а-яёa-z]+", fragment)
        candidates = []
        for i, action in enumerate(actions):
            if not action["complete"]:
                continue
            name_tokens = re.findall(r"[а-яёa-z]+", action["name"].casefold())
            if name_tokens and all(
                any(word.startswith(token[: max(3, len(token) - 2)]) for word in tokens)
                for token in name_tokens
            ):
                candidates.append(i)
        return candidates[0] if len(candidates) == 1 else None

    tail = body[total.end() :].strip(" ,:.")
    tail = re.sub(r"^[иа]\b", "", tail).strip(" ,:.")
    if len(actions) == 1 and actions[0]["complete"] and (not tail or identify(tail) == 0):
        return [0] * expected
    parts = re.split(r"[,;]|\s+и\s+", tail)
    sequence = []
    for part in parts:
        count = re.search(r"\b(" + "|".join(counts) + r"|\d+)\b", part)
        if not count:
            return []
        amount = counts.get(count[1], int(count[1]) if count[1].isdigit() else 0)
        index = identify(part)
        if index is None or not 1 <= amount <= 8:
            return []
        sequence.extend([index] * amount)
    return sequence if len(sequence) == expected else []


def validate(rules):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as schema_validate

    schema_validate(rules, schemas()["creature_actions_v2"])
    actions = rules["actions"]
    if any(
        index >= len(actions) or not actions[index]["complete"] for index in rules["multiattack"]
    ):
        raise ValueError("Invalid or partially implemented multiattack reference")
    if rules["multiattack_complete"] != bool(rules["multiattack"]):
        raise ValueError("Inconsistent multiattack completeness")


def selected(properties, index):
    rules = properties["source_actions_v2"]
    validate(rules)
    if type(index) is not int or not 0 <= index < len(rules["actions"]):
        raise ValueError("Invalid source attack index")
    action = rules["actions"][index]
    if not action["complete"]:
        raise ValueError("This source attack requires an additional handler")
    return action


def turn(engine, actor, target, properties):
    from rpg_vkr.domain.catalog_actions_v2 import hit

    rules = properties["source_actions_v2"]
    validate(rules)
    sequence = rules["multiattack"]
    if not sequence:
        available = [i for i, row in enumerate(rules["actions"]) if row["complete"]]
        if not available:
            hit(engine, actor, target)  # Existing, explicitly partial basic fallback.
            from rpg_vkr.world_library.creature_rules import after_attack

            after_attack(engine, actor, target, properties)
            return

        def average(index):
            row = rules["actions"][index]
            count, sides = re.match(r"(\d+)d(\d+)", row["dice"]).groups()
            modifier = re.search(r"([+-]\d+)$", row["dice"])
            return int(count) * (int(sides) + 1) / 2 + (int(modifier[1]) if modifier else 0)

        sequence = [max(available, key=average)]
        if len(rules["actions"]) == 1:
            sequence *= 1 + properties.get("source_extra_attacks", 0)
    for index in sequence:
        if engine.hp(actor) <= 0 or engine.hp(target) <= 0:
            break
        hit(engine, actor, target, source_attack=index)
