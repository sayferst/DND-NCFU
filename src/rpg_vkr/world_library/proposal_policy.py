"""Normalize original model-authored templates without conflating provenance with execution."""

from copy import deepcopy

VERSION = "world-proposal-1"


def register(spec):
    trace = {"type": "string", "minLength": 1, "maxLength": 128}
    spec["record"]["properties"]["provenance"]["properties"].update(
        model=deepcopy(trace),
        prompt_version=deepcopy(trace),
        engine_version=deepcopy(trace),
    )
    spec["npc"]["properties"].update(
        social_version={"type": "string", "enum": ["library-social-1"]},
        can_trade={"type": "boolean"},
    )
    for profile in ("food", "medicine", "poison", "book", "quest"):
        spec[profile]["properties"]["utility_version"] = {
            "type": "string",
            "enum": ["library-utility-1"],
        }
    proposed_record = deepcopy(spec["record"])
    proposed_record["required"] = [
        key for key in proposed_record["required"] if key not in {"id", "provenance"}
    ]
    spec["authored_proposal"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "record": proposed_record,
            "model": deepcopy(trace),
            "prompt_version": deepcopy(trace),
        },
        "required": ["record", "model", "prompt_version"],
    }


def prepare_record(raw, *, model, prompt_version):
    from rpg_vkr.world_library.model import digest, dump, validate_record

    if any(
        type(value) is not str or not 1 <= len(value) <= 128 for value in (model, prompt_version)
    ):
        raise ValueError("Model and prompt version required, <=128 characters")
    if type(raw) is not dict or len(dump(raw)) > 64000:
        raise ValueError("One bounded authored template required")
    row = deepcopy(raw)
    if type(row.get("attributes")) is not dict:
        raise ValueError("Typed attributes required")
    provenance = row.setdefault(
        "provenance",
        {
            "origin": "invented/homebrew",
            "source": "DND-NCFU original reviewed proposal",
            "generator": VERSION,
            "review": "unreviewed",
        },
    )
    if type(provenance) is not dict or provenance.get("origin") != "invented/homebrew":
        raise ValueError("Model-authored templates must be marked invented/homebrew")
    provenance.update(
        model=model,
        prompt_version=prompt_version,
        engine_version=VERSION + "/catalog3",
        review="unreviewed",
    )
    a = row["attributes"]
    if row.get("profile") == "npc":
        if not {"abilities", "armour_class", "damage_dice"} <= a.keys():
            raise ValueError("A new NPC needs all six abilities, armour class and damage dice")
        if a.get("social_version", "library-social-1") != "library-social-1":
            raise ValueError("Unknown NPC social contract")
        a["social_version"] = "library-social-1"
    if row.get("profile") in {"food", "medicine", "poison", "book", "quest"}:
        if a.get("utility_version", "library-utility-1") != "library-utility-1":
            raise ValueError("Unknown utility contract")
        a["utility_version"] = "library-utility-1"
    if "id" not in row:
        row["id"] = "gm_" + digest({"version": VERSION, "record": row})[:40]
    validate_record(row)
    if row["profile"] != "npc" and any(
        link["relation"] == "starting_inventory" for link in row["links"]
    ):
        raise ValueError("Initial inventory creation is currently an NPC contract")
    return row
