"""Library NPCs attack with the actual intact item they hold, using finite ammunition."""

from dataclasses import replace


def weapon(engine, actor):
    actor_state = engine.actors[actor].state or {}
    if actor_state.get("library_inventory_version") != 1:
        return None
    id = actor_state.get("library_weapon")
    if not id:
        return None
    cost = max(1, 1 + engine.status_power(actor, "slow") - engine.status_power(actor, "haste"))
    if actor_state.get("st", 10) < cost:
        return None
    unarmed = {"category": "unarmed", "dice": "1d4", "kind": "weapon"}
    entity = engine.actors.get(id)
    if not entity or entity.owner_id != actor or entity.parent_id != actor:
        return unarmed
    definition = engine.definitions[entity.definition_id]
    rules = definition.properties.get("library_item_rules")
    if not rules or rules["kind"] != "weapon" or (entity.state or {}).get("condition", 0) <= 0:
        return unarmed
    from rpg_vkr.world_library.equipment_rules import validate_equipment

    validate_equipment(rules)
    result = dict(rules)
    if rules["required_ammunition"]:
        ammunition = None
        for candidate in engine.actors.values():
            if candidate.owner_id != actor or candidate.parent_id != actor:
                continue
            value = engine.definitions[candidate.definition_id].properties.get("library_item_rules")
            if (
                value
                and value["category"] == "ammunition"
                and value["ammo_kind"] == rules["required_ammunition"]
                and candidate.quantity > 0
            ):
                ammunition = candidate
                break
        if ammunition is None:
            return unarmed
        if ammunition.quantity == 1:
            engine.actors.pop(ammunition.id)
            engine.things.pop(ammunition.id, None)
            engine.state["items"] = [
                item
                for item in engine.state["items"]
                if item.get("source", item["id"]) != ammunition.id
            ]
        else:
            engine.actors[ammunition.id] = replace(ammunition, quantity=ammunition.quantity - 1)
            if ammunition.id in engine.things:
                engine.things[ammunition.id] = replace(
                    engine.things[ammunition.id], quantity=ammunition.quantity - 1
                )
            for item in engine.state["items"]:
                if item.get("source", item["id"]) == ammunition.id:
                    item["quantity"] = ammunition.quantity - 1
        engine.events.append(
            {
                "kind": "library_npc_ammunition",
                "actor": actor,
                "instance": ammunition.id,
                "consumed": 1,
            }
        )
    state = dict(entity.state or {})
    state["condition"] -= 1
    engine.actors[id] = replace(entity, state=state)
    for item in engine.state["items"]:
        if item.get("source", item["id"]) == id:
            item["durability"] = state["condition"]
    engine.events.append(
        {
            "kind": "library_npc_weapon",
            "actor": actor,
            "instance": id,
            "condition": state["condition"],
        }
    )
    return result
