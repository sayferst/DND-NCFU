"""Versioned original food, medicine, fictional poison, reading and examination."""

from rpg_vkr.domain.character import ability_modifier

VERSION = "library-utility-1"
PROFILES = {"food", "medicine", "poison", "book", "quest"}


def compile_utility(record):
    profile, a = record["profile"], record["attributes"]
    if profile not in PROFILES:
        raise ValueError("Unsupported utility profile")
    power = a.get("potency", a.get("nutrition", 1))
    rules = {
        "version": VERSION,
        "profile": profile,
        "power": power,
        "shelf_days": a.get("shelf_days", 0),
        "minutes": 10 if profile == "book" else 1,
    }
    validate(rules)
    return rules


def validate(rules):
    if set(rules) != {"version", "profile", "power", "shelf_days", "minutes"}:
        raise ValueError("Unknown utility instructions")
    if rules["version"] != VERSION or rules["profile"] not in PROFILES:
        raise ValueError("Unknown utility version")
    for key, lo, hi in (("power", 1, 20), ("shelf_days", 0, 3650), ("minutes", 1, 60)):
        if type(rules[key]) is not int or not lo <= rules[key] <= hi:
            raise ValueError("Utility outside balance bounds")


def perform(engine, args):
    if engine.state.get("catalog_revision") != 3:
        raise ValueError("Utility requires canonical catalog3")
    if set(args) - {"item", "target"} or "item" not in args:
        raise ValueError("Specify one item instance and one target")
    item = engine.owned(args["item"])
    entity = engine.actors[item.get("source", item["id"])]
    definition = engine.definitions[entity.definition_id]
    rules = definition.properties.get("library_utility_rules")
    if not rules:
        raise ValueError("This instance has no utility handler")
    validate(rules)
    if item["durability"] <= 0:
        raise ValueError("The item is unusable")
    profile = rules["profile"]
    target = args.get("target", "hero")
    if not isinstance(target, str):
        raise ValueError("Target must be an instance ID")
    if target != "hero":
        engine.actor(target, alive=False)
        if engine.refs[target].place != engine.scene.current:
            raise ValueError("Target is outside this scene")
    if profile != "medicine" and profile != "poison" and target != "hero":
        raise ValueError("Reading and eating apply to the hero")
    if profile == "poison" and (
        target == "hero"
        or not engine.state["battle"]
        or engine.state["battle"]["sides"].get(target) != "enemy"
        or engine.hp(target) <= 0
    ):
        raise ValueError("Fictional poison requires a living enemy in the encounter")
    if profile == "medicine" and engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import life

        if life(engine, target).dead:
            raise ValueError("Ordinary medicine cannot revive a dead creature")
    if profile == "medicine" and target != "hero":
        if (engine.actor(target, False)[0].state or {}).get("life") == "dead":
            raise ValueError("Ordinary medicine cannot revive a dead creature")
    if profile == "food":
        created = (entity.state or {}).get("library_created_minute")
        if type(created) is not int:
            raise ValueError("Food freshness needs its creation timestamp")
        if engine.state["minute"] - created >= rules["shelf_days"] * 1440:
            raise ValueError("This food has spoiled")
    engine.action_minutes = rules["minutes"]
    if engine.state["battle"] and rules["minutes"] > 1:
        raise ValueError("Finish the encounter before extended reading")
    if profile in {"medicine", "poison", "food"}:
        engine.consume_item(item)
    before = engine.hp(target)
    if profile == "medicine":
        engine.change_hp(target, 2 * rules["power"])
    elif profile == "food":
        engine.state["st"] = min(engine.state["st_cap"], engine.state["st"] + rules["power"])
        nutrition = engine.state.setdefault("library_nutrition", {})
        nutrition["satiated_until"] = max(
            nutrition.get("satiated_until", 0), engine.state["minute"] + 60 * rules["power"]
        )
    elif profile == "poison":
        # Delivering a fictional combat powder is an action with an ordinary engine check.
        if engine.check("alchemy", max(10, engine.defence(target))):
            from rpg_vkr.world_library.source_runtime import enabled, saving_throw

            dc = 10 + rules["power"]
            if enabled(engine):
                saved = saving_throw(engine, target, "constitution", dc)
            else:
                bonus = ability_modifier(
                    engine.actor(target, False)[1].properties.get("constitution", 10)
                )
                natural = engine.roll("1d20", "Стойкость к вымышленному яду")
                if engine.state.get("owner_rules_policy") == 1:
                    from rpg_vkr.domain.owner_rules import check
                    from rpg_vkr.domain.owner_rules_runtime import life

                    result = check(
                        natural,
                        bonus,
                        dc,
                        exhaustion=life(engine, target).exhaustion,
                        partial=False,
                    )
                    saved = result["succeeded"]
                    if result["complication"]:
                        engine.owner_complication_minutes = (
                            getattr(engine, "owner_complication_minutes", 0) + 1
                        )
                else:
                    saved = natural + bonus >= dc
            if not saved:
                amount = engine.roll("1d4", "Урон вымышленного яда") + rules["power"]
                engine.damage(target, amount, "poison", "hero")
    else:
        from dataclasses import replace

        engine.state.setdefault("library_knowledge", {})[definition.id] = {
            "instance_id": entity.id,
            "digest": definition.properties["library_digest"],
            "minute": engine.state["minute"],
            "kind": profile,
        }
        item["durability"] = max(0, item["durability"] - 1)
        engine.actors[entity.id] = replace(
            entity, state=dict(entity.state or {}) | {"condition": item["durability"]}
        )
    engine.events.append(
        {
            "kind": "library_utility",
            "version": VERSION,
            "profile": profile,
            "instance": entity.id,
            "definition": definition.id,
            "target": target,
            "hp_delta": engine.hp(target) - before,
            "consumed": profile in {"medicine", "poison", "food"},
        }
    )
    engine.text.append(
        {
            "medicine": "Применено вымышленное лекарство",
            "poison": "Предпринята попытка применения вымышленного яда",
            "food": "Съедена порция",
            "book": "Прочитана книга",
            "quest": "Осмотрен квестовый предмет",
        }[profile]
        + ": "
        + definition.name
    )
