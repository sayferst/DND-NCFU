"""MP-adapted finite source spells. Programs are data; all effects run in Python."""

VERSION = "library-source-magic-1"


def mp_cost(level):
    if type(level) is not int or not 0 <= level <= 9:
        raise ValueError("Source spell level outside the supported MP system")
    return 1 if level == 0 else 2 * level + 2


def register(spec):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "level": {"type": "integer", "enum": [0]},
            "mp": {"type": "integer", "enum": [1]},
            "mode": {"type": "string", "enum": ["ranged_attack", "constitution_save"]},
            "range_ft": {"type": "integer", "minimum": 1, "maximum": 120},
            "dice": {"type": "string", "enum": ["1d12"]},
            "element": {"type": "string", "enum": ["poison"]},
            "source_prose_sha256": {"type": "string", "pattern": "[a-f0-9]{64}", "maxLength": 64},
            "adaptation": {
                "type": "string",
                "enum": ["MP; reviewed formula grants use; scene geometry"],
            },
        },
        "required": [
            "version",
            "level",
            "mp",
            "mode",
            "range_ft",
            "dice",
            "element",
            "source_prose_sha256",
            "adaptation",
        ],
    }
    states = spec["source_reference"]["properties"]["mechanics_state"]["enum"]
    if "mp-adapted" not in states:
        states.append("mp-adapted")
    spec["source_spell_v1"] = schema
    spec["source_reference"]["properties"]["source_spell_v1"] = schema


def validate(program):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as schema_validate

    schema_validate(program, schemas()["source_spell_v1"])
    if program["mp"] != mp_cost(program["level"]):
        raise ValueError("Source MP cost mismatch")
    expected = 30 if program["mode"] == "ranged_attack" else 10
    if program["range_ft"] != expected:
        raise ValueError("Source spell mode/range mismatch")


def perform(engine, args):
    from rpg_vkr.domain.catalog_actions_v2 import level
    from rpg_vkr.world_library import source_runtime
    from rpg_vkr.world_library.damage_packets import apply as damage_packet
    from rpg_vkr.world_library.source_geometry import distance

    if set(args) != {"item", "target"}:
        raise ValueError("Source formula requires one item and one target")
    item = engine.owned(args["item"])
    entity = engine.actors[item.get("source", item["id"])]
    definition = engine.definitions[entity.definition_id]
    program = definition.properties["library_source_spell"]
    validate(program)
    target = args["target"]
    if type(target) is not str:
        raise ValueError("Target must be an actor ID")
    engine.actor(target)
    if item["quantity"] != 1 or item["durability"] <= 0 or engine.state["mp"] < program["mp"]:
        raise ValueError("One intact owned formula and sufficient MP required")
    if (
        not engine.state["battle"]
        or engine.state["battle"]["sides"].get(target) != "enemy"
        or source_runtime.incapacitated(engine, "hero")
        or source_runtime.has(engine, "hero", "blinded")
        or source_runtime.has(engine, target, "invisible")
    ):
        raise ValueError("Source spell requires a visible enemy and conscious caster")
    if distance(engine, "hero", target) > program["range_ft"]:
        raise ValueError("Source spell target outside range")
    engine.state["mp"] -= program["mp"]
    task = "faith" if engine.state["identity"]["class_id"] == "cleric" else "arcana"
    bonus = engine.hero_bonus(task)
    critical = False
    if program["mode"] == "constitution_save":
        success = not source_runtime.saving_throw(
            engine, target, "constitution", 8 + bonus, magical=True
        )
    else:
        mode = source_runtime.attack_mode(engine, "hero", target, True)
        natural = source_runtime.roll_d20(engine, mode, "Атака исходного заклинания")
        if engine.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules_runtime import life

            bonus -= 2 * life(engine, "hero").exhaustion
            if natural == 1:
                engine.owner_complication_minutes = (
                    getattr(engine, "owner_complication_minutes", 0) + 1
                )
                engine.events.append(
                    {"kind": "owner_complication", "consequence": "lost_tempo", "minutes": 1}
                )
        critical = natural == 20
        success = critical or natural != 1 and natural + bonus >= engine.defence(target)
    amount = delivered = 0
    if success:
        dice = str(1 + sum(level(engine) >= n for n in (5, 11, 17))) + "d12"
        amount = engine.roll(dice, "Урон исходного заклинания")
        if critical:
            amount += engine.roll(dice, "Критический урон исходного заклинания")
        if engine.state.get("owner_rules_policy") == 1:
            engine.owner_hit_flags = {"critical": critical, "nonlethal": False}
        delivered = damage_packet(engine, target, [(amount, "poison")], "hero")
        engine.owner_hit_flags = {}
    engine.events.append(
        {
            "kind": "source_spell",
            "version": VERSION,
            "instance": entity.id,
            "formula": definition.id,
            "target": target,
            "mp_spent": program["mp"],
            "mode": program["mode"],
            "hit": success,
            "critical": critical,
            "damage": delivered,
        }
    )
    engine.text.append("Применена формула с расходом MP: " + definition.name)
