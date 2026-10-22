"""Individual, local observations and relationship updates from generic transfers."""

from dataclasses import replace

from rpg_vkr.domain.interactions import WorldPlan, apply_plan


def react(catalog, record, turn_index):
    if record.before.version != "interactive-world-4":
        return catalog
    definitions = {d.id: d for d in catalog.definitions}
    entities = {e.id: e for e in catalog.entities}
    for index, step in enumerate(record.plan.steps):
        if step.op not in {"take", "give"}:
            continue
        prefix = record.plan.steps[:index]
        visited = {s.target for s in prefix if s.op == "move"}
        state, prefix_risky, _, _ = apply_plan(
            record.before,
            WorldPlan(prefix, tuple(p for p in record.plan.places if p.id in visited)),
            turn_index=turn_index,
        )
        if record.check and not record.check.succeeded and prefix_risky:
            break
        item = next(t for t in state.things if t.id == step.target)
        theft = (
            step.op == "take"
            and item.owner not in {"", "hero"}
            and state.root_holder(item) != "hero"
        )
        gift = step.op == "give" and item.owner == "hero"
        if not (theft or gift):
            continue
        for actor in state.actor_refs:
            entity = entities.get(actor.id)
            if not entity or actor.place != state.current:
                continue
            definition = definitions[entity.definition_id]
            status = dict(entity.state or {})
            if status.get("hp", 1) <= 0 or status.get("asleep") or status.get("can_see") is False:
                continue
            relations = dict(status.get("relations", {}))
            hero = dict(relations.get("hero", {}))
            if theft:
                victim = item.owner == actor.id
                hero["grievance"] = min(10, hero.get("grievance", 0) + (3 if victim else 1))
                hero["fear"] = min(10, hero.get("fear", 0) + (0 if victim else 1))
                courage = definition.properties.get("courage", 3)
                protects = definition.properties.get("protects_others", False)
                if type(courage) is not int or not 0 <= courage <= 10 or type(protects) is not bool:
                    raise ValueError("Некорректная политика реакции NPC.")
                if (
                    (victim or protects)
                    and courage >= 5
                    and hero["grievance"] > hero.get("trust", 0)
                ):
                    status["disposition"] = "hostile"
                status["last_observed_event"] = {
                    "kind": "theft"
                    if not record.check or record.check.succeeded
                    else "theft_attempt",
                    "turn": turn_index,
                    "place": state.current,
                    "item": item.id,
                    "victim": item.owner,
                }
            elif gift and actor.id == step.destination:
                item_entity = entities.get(item.id)
                item_type = (
                    item_entity.definition_id
                    if item_entity
                    else {"bandages": "type_bandage"}.get(item.resource)
                )
                item_definition = definitions.get(item_type)
                valued = (
                    item.resource == "gold"
                    or item_definition
                    and (
                        (item_definition.price_cp or 0) > 0
                        or item_type in definition.properties.get("wanted_types", [])
                    )
                )
                if valued:
                    hero["trust"] = min(10, hero.get("trust", 0) + 1)
                status["last_observed_event"] = {
                    "kind": "gift",
                    "turn": turn_index,
                    "place": state.current,
                    "item": item.id,
                }
            else:
                continue
            relations["hero"] = hero
            status["relations"] = relations
            entities[actor.id] = replace(entity, state=status)
    return replace(catalog, entities=tuple(entities[e.id] for e in catalog.entities))
