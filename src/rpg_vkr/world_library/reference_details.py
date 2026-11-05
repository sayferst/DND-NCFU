"""Typed factual models for source records; descriptive text is not an executable rule."""

import re


def register(spec):
    def text(limit=200):
        return {"type": "string", "maxLength": limit}

    def integer(low=-1, high=1000000000):
        return {"type": "integer", "minimum": low, "maximum": high}

    def array(item, maximum=100):
        return {"type": "array", "items": item, "maxItems": maximum}

    def obj(fields):
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }

    boolean = {"type": "boolean"}
    progression = obj({"level": integer(1, 20), "proficiency": integer(0, 10)})
    values = {
        "class": obj(
            {
                "source_class_id": text(),
                "parent_global_id": text(64),
                "minimum_level": integer(-1, 1000),
                "hit_die_sides": integer(-1, 100),
                "progression": array(progression, 20),
                "child_ids": array(text(64), 500),
                "source_dice": array(text(60)),
                "source_fields": array(text(80)),
            }
        ),
        "spell": obj(
            {
                "level": integer(-1, 100),
                "school": text(100),
                "casting_unit": text(30),
                "casting_amount": integer(),
                "range_kind": text(30),
                "range_feet": integer(),
                "duration_kind": text(30),
                "duration_seconds": integer(),
                "components": array(text(30), 10),
                "class_names": array(text(100), 50),
                "ritual": boolean,
                "concentration": boolean,
                "source_dice": array(text(60)),
                "source_fields": array(text(80)),
            }
        ),
        "race": obj(
            {
                "creature_type": text(100),
                "sizes": array(text(40), 5),
                "speed_walk_ft": integer(),
                "speed_fly_ft": integer(),
                "speed_swim_ft": integer(),
                "speed_climb_ft": integer(),
                "darkvision_ft": integer(),
                "languages": array(text(100), 50),
                "skill_names": array(text(100), 50),
                "ability_bonuses": array(obj({"ability": text(30), "bonus": integer(-10, 10)}), 20),
                "parent_global_id": text(64),
                "child_ids": array(text(64), 100),
                "source_dice": array(text(60)),
                "source_fields": array(text(80)),
            }
        ),
        "trait": obj(
            {
                "minimum_level": integer(-1, 1000),
                "prerequisite_mode": text(30),
                "ability_requirements": array(
                    obj({"ability": text(30), "minimum": integer(1, 40)}), 10
                ),
                "required_classes": array(text(100), 50),
                "required_races": array(text(100), 50),
                "required_skills": array(text(100), 50),
                "required_spells": array(text(100), 50),
                "required_feats": array(text(100), 50),
                "other_prerequisite_present": boolean,
                "ability_increases": array(
                    obj(
                        {
                            "ability": text(100),
                            "amount": integer(-10, 10),
                            "maximum": integer(-1, 40),
                        }
                    ),
                    20,
                ),
                "armour_class_bonus": integer(-10, 10),
                "spellcasting_ability": text(100),
                "granted_spells": array(text(100), 50),
                "granted_skills": array(text(100), 50),
                "granted_tools": array(text(100), 50),
                "granted_weapons": array(text(100), 50),
                "granted_armour": array(text(100), 50),
                "custom_rule_count": integer(0, 1000),
                "tags": array(text(100), 50),
                "source_dice": array(text(60)),
                "source_fields": array(text(80)),
            }
        ),
        "magic_item": obj(
            {
                "rarity": text(100),
                "item_type": text(150),
                "subtype": text(150),
                "requires_attunement": boolean,
                "charges_max": integer(),
                "source_price": text(150),
                "source_dice": array(text(60)),
                "source_fields": array(text(80)),
            }
        ),
        "background": obj(
            {
                "skill_names": array(text(100), 50),
                "tool_names": array(text(100), 50),
                "language_names": array(text(100), 50),
                "source_dice": array(text(60)),
                "source_fields": array(text(80)),
            }
        ),
        "other": obj(
            {
                "source_fields": array(text(80)),
                "source_dice": array(text(60)),
                "node_role": text(50),
                "numeric_parameters": array(
                    obj({"field": text(120), "value": integer(-1000000000, 1000000000)})
                ),
                "boolean_parameters": array(obj({"field": text(120), "value": boolean})),
                "outcome_count": integer(),
                "die_sides": integer(),
            }
        ),
    }
    for name, value in values.items():
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        spec["reference_" + name] = value
    attrs = spec["source_reference"]["properties"]
    attrs.update(
        record_type={"type": "string", "enum": list(values)},
        details={"type": "object"},
        source_asset=text(1000),
        source_asset_sha256=text(64),
        data_state={
            "type": "string",
            "enum": [
                "source-structured",
                "source-section",
                "needs-source-resolution",
                "index-control",
            ],
        },
    )


def validate_details(attributes, spec, validate):
    fields = {"record_type", "details", "source_asset", "source_asset_sha256", "data_state"}
    if fields & attributes.keys():
        if not fields <= attributes.keys():
            raise ValueError("Incomplete source details envelope")
        validate(attributes["details"], spec["reference_" + attributes["record_type"]], "details")
        fingerprint = attributes["source_asset_sha256"]
        if fingerprint and not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("Invalid source asset fingerprint")
        if attributes["data_state"] in {"source-structured", "source-section"} and not fingerprint:
            raise ValueError("Structured source requires asset fingerprint")
