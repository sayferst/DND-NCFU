"""Versioned numerical adapter; extracted facts and homebrew fallbacks stay distinct."""

import re
from fractions import Fraction

from rpg_vkr.domain.character import ability_modifier

VERSION = "library-creature-1"


def compile_creature(record):
    a = record["attributes"]
    try:
        cr = max(0, min(30, float(Fraction(a["challenge_rating"] or "1"))))
    except (ValueError, ZeroDivisionError):
        cr = 1
    invented = []
    hp = a["hp"]
    if not hp:
        hp = max(4, int(8 + cr * 12))
        invented.append("hp_max")
    ac = a["armour_class"]
    if not ac:
        ac = min(25, 10 + int(cr / 3))
        invented.append("armour_class")
    stats = {}
    for short, full in zip(
        ("str", "dex", "con", "int", "wis", "cha"),
        ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"),
        strict=True,
    ):
        stats[full] = a["abilities"][short] or 10
        if not a["abilities"][short]:
            invented.append(full)
    # A fallback is a declared homebrew basic attack, not a claimed source feature.
    bonus = ability_modifier(stats["strength"]) + min(9, 2 + int(cr // 4))
    dice = "1d6"
    invented.extend(["attack_bonus", "damage_dice"])
    if a.get("attacks"):
        bonus, dice = a["attacks"][0]["bonus"], a["attacks"][0]["dice"]
        invented = [key for key in invented if key not in {"attack_bonus", "damage_dice"}]
    implemented = {
        attack["name"] for attack in a.get("attacks", [])[:1] if not attack.get("partial")
    }
    if a.get("regeneration"):
        implemented.update(name for name in a["feature_names"] if "регенерац" in name.casefold())
    if a.get("extra_attacks"):
        implemented.add("Мультиатака")
    version = VERSION
    extended = {}
    if "actions_v2" in a:
        from rpg_vkr.world_library.creature_actions import VERSION as ACTIONS_VERSION
        from rpg_vkr.world_library.creature_actions import validate

        validate(a["actions_v2"])
        version = ACTIONS_VERSION
        extended["source_actions_v2"] = a["actions_v2"]
        if a.get("attack_math_version") == 2:
            extended["source_attack_math_version"] = 2
            if a["actions_v2"]["actions"]:
                first = a["actions_v2"]["actions"][0]
                bonus, dice = first["bonus"], first["dice"]
                invented = [key for key in invented if key not in {"attack_bonus", "damage_dice"}]
                extended["source_attack_element"] = first["element"]
        for field, flag in (
            ("source_resistances", "force_resistance"),
            ("source_immunities", "force_immunity"),
            ("source_vulnerabilities", "force_vulnerability"),
        ):
            if a["actions_v2"].get(flag):
                extended[field] = sorted(set(a[field.removeprefix("source_")]) | {"force"})
        implemented = set()
        if a.get("regeneration"):
            implemented.update(
                name for name in a["feature_names"] if "регенерац" in name.casefold()
            )
        if a.get("extra_attacks"):
            implemented.add("Мультиатака")
        implemented.update(
            action["name"] for action in a["actions_v2"]["actions"] if action["complete"]
        )
        if a["actions_v2"]["multiattack_complete"]:
            implemented.add("Мультиатака")
    if "features_v3" in a:
        from rpg_vkr.world_library.source_extract import validate as validate_source
        from rpg_vkr.world_library.source_runtime import VERSION as SOURCE_VERSION

        validate_source(a["features_v3"], a["actions_v2"])
        version = SOURCE_VERSION
        extended["source_features_v3"] = a["features_v3"]
        implemented.update(a["features_v3"]["supported_names"])
    if "resilience_v1" in a:
        from rpg_vkr.world_library.resilience_rules import validate as validate_resilience

        validate_resilience(a["resilience_v1"])
        extended["library_resilience_rules"] = a["resilience_v1"]
        implemented.update(a["resilience_v1"]["supported_names"])
    if "regeneration_v1" in a:
        from rpg_vkr.world_library.regeneration_rules import validate as validate_regeneration

        validate_regeneration(a["regeneration_v1"])
        extended["library_regeneration_rules"] = a["regeneration_v1"]
        implemented.update(a["regeneration_v1"]["supported_names"])
    extended["library_creature_size"] = a["source_size"]
    if "skill_bonuses_v1" in a:
        extended["library_check_bonuses"] = a["skill_bonuses_v1"]
    if "grapple_v1" in a:
        from rpg_vkr.world_library.grapple_rules import validate as validate_grapple

        validate_grapple(a["grapple_v1"], a["actions_v2"]["actions"])
        extended["library_grapple_rules"] = a["grapple_v1"]
        if any(rule["max_size"] < 0 for rule in a["grapple_v1"]["attacks"]):
            invented.append("grapple_target_size_limit")
    if "multiattack_v1" in a:
        from rpg_vkr.world_library.multiattack_rules import validate as validate_multiattack

        validate_multiattack(a["multiattack_v1"], a["actions_v2"]["actions"], a["features_v3"])
        extended["library_multiattack_rules"] = a["multiattack_v1"]
        implemented.add("Мультиатака")
    return {
        "hp_max": hp,
        "armour_class": ac,
        **stats,
        "damage_dice": dice,
        "attack_bonus": bonus,
        "attack_damage": max(1, 3 + ability_modifier(stats["strength"])),
        "library_rules_version": version,
        "homebrew_fields": invented,
        "unsupported_source_features": [
            name for name in a["feature_names"] if name not in implemented
        ],
        "source_resistances": a.get("resistances", []),
        "source_immunities": a.get("immunities", []),
        "source_vulnerabilities": a.get("vulnerabilities", []),
        "source_regeneration": a.get("regeneration", 0),
        "source_extra_attacks": a.get("extra_attacks", 0),
        "source_attack_element": a["attacks"][0].get("element", "physical")
        if a.get("attacks")
        else "physical",
        "behavior": "hunter",
        **extended,
    }


def validate_runtime(properties):
    from rpg_vkr.world_library.creature_actions import VERSION as ACTIONS_VERSION
    from rpg_vkr.world_library.creature_actions import validate
    from rpg_vkr.world_library.source_runtime import VERSION as SOURCE_VERSION

    if "source_attack_math_version" in properties and (
        type(properties["source_attack_math_version"]) is not int
        or properties["source_attack_math_version"] != 2
    ):
        raise ValueError("Unknown source attack math version")
    if properties.get("library_rules_version") not in {VERSION, ACTIONS_VERSION, SOURCE_VERSION}:
        raise ValueError("Unknown library creature rules")
    if properties["library_rules_version"] in {ACTIONS_VERSION, SOURCE_VERSION}:
        validate(properties["source_actions_v2"])
    if properties["library_rules_version"] == SOURCE_VERSION:
        from rpg_vkr.world_library.source_extract import validate as validate_source

        validate_source(properties["source_features_v3"], properties["source_actions_v2"])
    if (
        type(properties.get("attack_bonus")) is not int
        or not -10 <= properties["attack_bonus"] <= 40
    ):
        raise ValueError("Invalid attack bonus")
    pattern = r"[1-9][0-9]?d(?:4|6|8|10|12)(?:[+-][0-9]{1,2})?"
    if properties.get("source_attack_math_version") == 2:
        from rpg_vkr.world_library.creature_actions import DICE

        pattern = DICE
    if not re.fullmatch(pattern, properties.get("damage_dice", "")):
        raise ValueError("Invalid creature damage dice")
    if "library_grapple_rules" in properties:
        from rpg_vkr.world_library.grapple_rules import validate as validate_grapple

        validate_grapple(
            properties["library_grapple_rules"], properties["source_actions_v2"]["actions"]
        )
    if "library_multiattack_rules" in properties:
        from rpg_vkr.world_library.multiattack_rules import validate as validate_multiattack

        validate_multiattack(
            properties["library_multiattack_rules"],
            properties["source_actions_v2"]["actions"],
            properties["source_features_v3"],
        )
    elements = {
        "fire",
        "cold",
        "lightning",
        "acid",
        "poison",
        "necrotic",
        "radiant",
        "psychic",
        "thunder",
    }
    if properties["library_rules_version"] in {ACTIONS_VERSION, SOURCE_VERSION}:
        elements.add("force")
    if properties.get("source_attack_element", "physical") not in elements | {"physical"}:
        raise ValueError("Unknown creature attack element")
    for field in ("source_resistances", "source_immunities", "source_vulnerabilities"):
        if (
            not isinstance(properties.get(field, []), list)
            or not set(properties.get(field, [])) <= elements
        ):
            raise ValueError("Unknown creature damage element")
    for field, maximum in (("source_regeneration", 100), ("source_extra_attacks", 2)):
        if (
            type(properties.get(field, 0)) is not int
            or not 0 <= properties.get(field, 0) <= maximum
        ):
            raise ValueError("Creature feature outside balance bounds")


def incoming(properties, amount, element):
    validate_runtime(properties)
    if element in properties.get("source_immunities", []):
        return 0
    if element in properties.get("source_resistances", []):
        amount //= 2
    if element in properties.get("source_vulnerabilities", []):
        amount *= 2
    return amount


def before_turn(engine, id, properties):
    validate_runtime(properties)
    if "library_regeneration_rules" in properties:
        from rpg_vkr.world_library.regeneration_rules import start_turn

        if id not in getattr(engine, "_library_regen_started", set()):
            start_turn(engine, id)
        return
    amount = properties.get("source_regeneration", 0)
    if amount and engine.hp(id) > 0:
        before = engine.hp(id)
        engine.change_hp(id, amount)
        engine.events.append(
            {
                "kind": "source_regeneration",
                "actor": id,
                "healed": engine.hp(id) - before,
                "version": VERSION,
            }
        )


def after_attack(engine, id, target, properties):
    validate_runtime(properties)
    from rpg_vkr.domain.catalog_actions_v2 import hit

    for _ in range(properties.get("source_extra_attacks", 0)):
        if engine.hp(id) <= 0 or engine.hp(target) <= 0:
            break
        hit(engine, id, target)
