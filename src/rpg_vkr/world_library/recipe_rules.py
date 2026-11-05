"""Finite original recipes execute only against real owned instances and a station."""

from dataclasses import replace

VERSION = "library-recipe-1"


def validate(rules):
    expected = {
        "version",
        "minutes",
        "difficulty",
        "mode",
        "station",
        "inputs",
        "outputs",
        "labour_cp",
    }
    if not isinstance(rules, dict) or set(rules) != expected or rules["version"] != VERSION:
        raise ValueError("Unknown recipe program")
    if rules["mode"] not in {"craft", "salvage"} or rules["station"] not in {"forge", "workbench"}:
        raise ValueError("Unknown recipe mode/station")
    for key, low, high in (("minutes", 1, 10000), ("difficulty", 5, 25)):
        if type(rules[key]) is not int or not low <= rules[key] <= high:
            raise ValueError("Recipe outside balance envelope")
    if type(rules["labour_cp"]) is not int or not 0 <= rules["labour_cp"] <= 10 * rules["minutes"]:
        raise ValueError("Recipe labour exceeds its time budget")
    for key in ("inputs", "outputs"):
        if not isinstance(rules[key], list) or not 1 <= len(rules[key]) <= 12:
            raise ValueError("Recipe requires bounded inputs/outputs")
        seen = set()
        for row in rules[key]:
            if set(row) != {"definition", "quantity"} or row["definition"] in seen:
                raise ValueError("Duplicate/unknown recipe reference")
            from rpg_vkr.domain.interactions import identifier

            identifier(row["definition"])
            seen.add(row["definition"])
            if type(row["quantity"]) is not int or not 1 <= row["quantity"] <= 100:
                raise ValueError("Recipe quantity outside bounds")


def compile_recipe(record, links, definitions):
    a = record["attributes"]
    outputs = [link for link in links if link["relation"] == "output"]
    station = "workbench"
    if a["mode"] == "craft" and any(
        definitions[link["definition"]].properties.get("library_item_rules", {}).get("kind")
        in {"weapon", "armour"}
        for link in outputs
    ):
        station = "forge"
    result = {
        "version": VERSION,
        "minutes": a["minutes"],
        "difficulty": a["difficulty"],
        "mode": a["mode"],
        "station": station,
        "labour_cp": a["labour_cp"],
    }
    for field, relation in (("inputs", "input"), ("outputs", "output")):
        quantities = {}
        for link in links:
            if link["relation"] == relation:
                quantities[link["definition"]] = (
                    quantities.get(link["definition"], 0) + link["quantity"]
                )
        result[field] = [{"definition": id, "quantity": n} for id, n in quantities.items()]
    validate(result)
    return result


def perform(engine, args):
    if engine.state.get("catalog_revision") != 3 or set(args) != {"item"}:
        raise ValueError("A canonical owned recipe instance is required")
    card = engine.owned(args["item"])
    definition = engine.definitions[engine.actors[card["source"]].definition_id]
    rules = definition.properties.get("library_recipe_rules")
    validate(rules)
    for reference in rules["inputs"] + rules["outputs"]:
        if reference["definition"] not in engine.definitions:
            raise ValueError("Missing recipe definition")
    if any(
        engine.definitions[row["definition"]].kind not in {"item", "material"}
        for row in rules["outputs"]
    ):
        raise ValueError("A recipe cannot create an actor")
    ins = sum(
        (engine.definitions[row["definition"]].price_cp or 0) * row["quantity"]
        for row in rules["inputs"]
    )
    outs = sum(
        (engine.definitions[row["definition"]].price_cp or 0) * row["quantity"]
        for row in rules["outputs"]
    )
    if outs > ins + rules["labour_cp"]:
        raise ValueError("Recipe creates unbudgeted value")
    if engine.state["battle"]:
        raise ValueError("Crafting is unavailable during an encounter")
    if card["durability"] <= 0:
        raise ValueError("Recipe is unreadable")
    station = any(
        engine.scene.here(thing)
        and thing.id in engine.actors
        and engine.definitions[engine.actors[thing.id].definition_id].properties.get("station")
        == rules["station"]
        and (
            engine.definitions[engine.actors[thing.id].definition_id].properties.get("public")
            or thing.owner in {"hero", engine.scene.current}
        )
        for thing in engine.scene.things
    )
    if not station:
        raise ValueError("An accessible " + rules["station"] + " is required")
    tool = None
    for entity in sorted(engine.actors.values(), key=lambda e: e.id):
        properties = engine.definitions[entity.definition_id].properties
        row = properties.get("library_item_rules", {})
        if row.get("capability") != "tools" and not properties.get("game_template_id"):
            continue
        try:
            candidate = engine.owned(entity.id)
            template = engine.template(candidate)
        except (KeyError, ValueError):
            continue
        if template.get("capability") == "tools" and candidate["durability"] > 0:
            tool = candidate
            break
    if tool is None:
        raise ValueError("Intact owned crafting tools are required")
    selected = []
    for needed in rules["inputs"]:
        remaining = needed["quantity"]
        for entity in sorted(list(engine.actors.values()), key=lambda e: e.id):
            if entity.definition_id != needed["definition"] or entity.id in {
                card["source"],
                tool["source"],
            }:
                continue
            try:
                item = engine.owned(entity.id)
            except ValueError:
                continue
            take = min(remaining, item["quantity"])
            if take:
                selected.append((item, take))
                remaining -= take
            if not remaining:
                break
        if remaining:
            raise ValueError("Insufficient owned material: " + needed["definition"])
    # Eligibility is complete before spending resources or consuming RNG.
    success = engine.check("repair", rules["difficulty"])
    for item, count in selected:
        engine.consume_item(item, count)
        if item["quantity"]:
            id = item["source"]
            engine.actors[id] = replace(engine.actors[id], quantity=item["quantity"])
            if id in engine.things:
                engine.things[id] = replace(engine.things[id], quantity=item["quantity"])
    tool["durability"] -= 1
    tool_entity = engine.actors[tool["source"]]
    engine.actors[tool_entity.id] = replace(
        tool_entity, state=(tool_entity.state or {}) | {"condition": tool["durability"]}
    )
    made = []
    if success:
        from rpg_vkr.domain.catalog import Entity
        from rpg_vkr.domain.interactions import Thing

        for output in rules["outputs"]:
            target = engine.definitions[output["definition"]]
            id = engine.mint("library_craft")
            state = {"condition": target.properties.get("durability", 20), "made_by": "hero"}
            engine.actors[id] = Entity(id, target.id, "hero", "hero", output["quantity"], state)
            engine.things[id] = Thing(id, target.name[:80], "hero", "hero", output["quantity"])
            made.append(id)
    engine.action_minutes = rules["minutes"]
    engine.events.append(
        {
            "kind": "library_recipe",
            "version": VERSION,
            "recipe": definition.id,
            "success": success,
            "outputs": made,
        }
    )
    engine.text.append(
        "Работа завершена." if success else "Работа не удалась; материалы израсходованы."
    )
