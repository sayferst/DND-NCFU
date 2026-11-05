"""Closed, original homebrew formulas. No prose, SQL or model code is interpreted."""

VERSION = "library-magic-1"
ELEMENTS = [
    "physical",
    "fire",
    "cold",
    "lightning",
    "acid",
    "poison",
    "necrotic",
    "radiant",
    "psychic",
    "thunder",
    "force",
]


def register(spec):
    def integer(low, high):
        return {"type": "integer", "minimum": low, "maximum": high}

    effect = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["shield", "signal", "damage", "defence"]},
            "element": {"type": "string", "enum": ELEMENTS},
            "power": integer(1, 10),
            "duration": integer(0, 6),
            "dice": {"type": "string", "pattern": "[1-5]d4", "maxLength": 4},
        },
        "required": ["operation", "element", "power", "duration", "dice"],
        "additionalProperties": False,
    }
    # Optional, so previously issued descriptive seed versions still validate.
    spec["spell"]["properties"]["rules"] = effect
    spec["library_magic_runtime"] = {
        "type": "object",
        "properties": {
            "version": {"type": "string", "enum": [VERSION]},
            "mp": integer(1, 60),
            "level": integer(1, 9),
            "charges": integer(0, 1),
            "effects": {"type": "array", "items": effect, "minItems": 1, "maxItems": 2},
        },
        "required": ["version", "mp", "level", "charges", "effects"],
        "additionalProperties": False,
    }


def validate(rules):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as schema_validate

    schema_validate(rules, schemas()["library_magic_runtime"])
    minimum_mp = 0
    for effect in rules["effects"]:
        tier = int(effect["dice"][0])
        mode = ["shield", "signal", "damage", "defence"].index(effect["operation"])
        minimum_mp += 2 * tier + mode
        if rules["level"] < tier or effect["power"] != (2 * tier if mode == 0 else 1 + tier // 2):
            raise ValueError("Formula exceeds its level/power envelope")
        if effect["duration"] != (0 if mode == 2 else 1 + tier):
            raise ValueError("Formula duration exceeds its tier envelope")
        if effect["operation"] == "damage" and effect["duration"] != 0:
            raise ValueError("Damage formula must be instantaneous")
        if effect["operation"] != "damage" and not effect["duration"]:
            raise ValueError("Status formula requires bounded duration")
    if rules["mp"] < minimum_mp:
        raise ValueError("Formula MP below combined effect cost")


def compile_magic(record, dependencies):
    a, profile = record["attributes"], record["profile"]
    if profile == "spell":
        if "rules" not in a:
            raise ValueError("No executable handler for descriptive formula")
        result = {
            "version": VERSION,
            "mp": a["mp"],
            "level": a["level"],
            "charges": 0,
            "effects": [a["rules"]],
        }
    elif profile in {"rune", "scroll"}:
        if len(dependencies) != 1 or dependencies[0]["charges"]:
            raise ValueError("Carrier requires exactly one nonconsumable formula")
        result = dict(dependencies[0]) | {"charges": 1}
    elif profile == "combination":
        if len(dependencies) != 2 or any(r["charges"] for r in dependencies):
            raise ValueError("Combination requires exactly two formulas")
        result = {
            "version": VERSION,
            "mp": max(a["mp"], sum(r["mp"] for r in dependencies)),
            "level": max(a["level"], *(r["level"] for r in dependencies)),
            "charges": 0,
            "effects": [e for r in dependencies for e in r["effects"]],
        }
    else:
        raise ValueError("No magic handler for this profile")
    validate(result)
    return result


def perform(engine, args):
    if engine.state.get("catalog_revision") != 3:
        raise ValueError("Library formulas require canonical catalog3")
    if set(args) - {"item", "target"} or "item" not in args:
        raise ValueError("Specify a formula instance and one target")
    item = engine.owned(args["item"])
    entity = engine.actors[item.get("source", item["id"])]
    definition = engine.definitions[entity.definition_id]
    rules = definition.properties.get("library_magic_rules")
    if not rules:
        raise ValueError("This item has no checked magic handler")
    validate(rules)
    if item["quantity"] != 1 or item["durability"] <= 0:
        raise ValueError("Use one intact formula carrier")
    if engine.state["mp"] < rules["mp"]:
        raise ValueError("Insufficient MP")
    from rpg_vkr.domain.catalog_actions_v2 import level

    if level(engine) < rules["level"]:
        raise ValueError("Formula level is unavailable")
    target = args.get("target", "hero")
    if not isinstance(target, str):
        raise ValueError("Target must be an instance ID")
    if target != "hero":
        engine.actor(target)
        if engine.refs[target].place != engine.scene.current:
            raise ValueError("Formula target is outside this scene")
    if engine.hp(target) <= 0:
        raise ValueError("Formula target must be conscious")
    if any(effect["operation"] == "damage" for effect in rules["effects"]):
        if (
            target == "hero"
            or not engine.state["battle"]
            or engine.state["battle"]["sides"].get(target) != "enemy"
        ):
            raise ValueError("Damage formula requires an enemy in the current encounter")
    engine.state["mp"] -= rules["mp"]
    if rules["charges"]:
        engine.consume_item(item)
    for effect in rules["effects"]:
        operation = effect["operation"]
        if operation == "damage":
            damage(engine, target, effect)
        else:
            engine.status(
                target,
                "light" if operation == "signal" else operation,
                effect["power"],
                effect["duration"],
                effect["element"],
            )
    engine.events.append(
        {
            "kind": "library_magic",
            "version": VERSION,
            "formula": definition.id,
            "instance": entity.id,
            "target": target,
            "mp_spent": rules["mp"],
            "charge_spent": rules["charges"],
        }
    )
    engine.text.append("Применена авторская формула: " + definition.name)


def damage(engine, target, effect):
    task = "faith" if engine.state["identity"]["class_id"] == "cleric" else "arcana"
    natural = engine.roll("1d20", "Атака авторской формулы")
    bonus = engine.hero_bonus(task)
    defence = engine.defence(target)
    critical = natural == 20
    success = critical or natural != 1 and natural + bonus >= defence
    delivered = 0
    if success:
        amount = engine.roll(effect["dice"], "Урон авторской формулы")
        if critical:
            amount += engine.roll(effect["dice"], "Критический урон формулы")
        if engine.state.get("owner_rules_policy") == 1:
            engine.owner_hit_flags = {"critical": critical, "nonlethal": False}
        delivered = engine.damage(target, amount, effect["element"])
        engine.owner_hit_flags = {}
    engine.attacks.append(
        {
            "actor_id": "hero",
            "target_id": target,
            "hit": success,
            "damage": delivered,
            "attack_bonus": bonus,
            "total": natural + bonus,
            "defence": defence,
            "defeated": engine.hp(target) == 0,
            "resolver_version": VERSION,
        }
    )
