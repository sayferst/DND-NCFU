"""Finite original NPC mood transitions driven exclusively by engine receipts."""

from dataclasses import replace

VERSION = "library-social-1"
EVENTS = {
    "движок подтвердил выполненное обещание": "contract_completed",
    "движок подтвердил кражу собственности": "property_taken",
}
MOODS = {"wary", "calm", "angry"}


def compile_social(record):
    a = record["attributes"]
    rules = {"version": VERSION, "initial": a["initial_mood"], "transitions": []}
    for row in a["mood_transitions"]:
        if row["event"] not in EVENTS:
            raise ValueError("NPC transition needs a verified engine event")
        rules["transitions"].append(
            {"from": row["from"], "event": EVENTS[row["event"]], "to": row["to"]}
        )
    validate(rules)
    return rules


def validate(rules):
    if (
        type(rules) is not dict
        or set(rules) != {"version", "initial", "transitions"}
        or rules["version"] != VERSION
        or type(rules["initial"]) is not str
        or rules["initial"] not in MOODS
        or type(rules["transitions"]) is not list
        or len(rules["transitions"]) > 6
    ):
        raise ValueError("Invalid NPC social program")
    seen = set()
    for row in rules["transitions"]:
        if (
            type(row) is not dict
            or set(row) != {"from", "event", "to"}
            or any(type(row[key]) is not str for key in ("from", "event", "to"))
            or row["from"] not in MOODS
            or row["to"] not in MOODS
            or row["event"] not in EVENTS.values()
        ):
            raise ValueError("Unknown social transition")
        key = row["from"], row["event"]
        if key in seen:
            raise ValueError("Ambiguous social transition")
        seen.add(key)


def update(engine):
    """Run once per new receipt; neither story prose nor old NPCs trigger this."""
    events = list(engine.events)
    first = getattr(engine, "_library_social_processed", 0)
    for event in events[first:]:
        if event.get("kind") == "contract_completed":
            actor, kind = event.get("npc"), "contract_completed"
        elif event.get("kind") == "owner_physical_take":
            actor, kind = event.get("legal_owner_after"), "property_taken"
            if event.get("holder_after") != "hero":
                continue
        else:
            continue
        entity = engine.actors.get(actor)
        if not entity or (entity.state or {}).get("library_social_version") != 1:
            continue
        rules = engine.definitions[entity.definition_id].properties.get("library_social_rules")
        if not rules:
            continue
        validate(rules)
        if kind == "property_taken":
            # An absent, dead, unconscious or blinded owner cannot witness a taking.
            ref = engine.refs.get(actor)
            state = entity.state or {}
            if (
                not ref
                or ref.place != engine.scene.current
                or engine.hp(actor) <= 0
                or state.get("asleep")
                or state.get("can_see") is False
            ):
                continue
            from rpg_vkr.world_library.source_runtime import enabled, has, incapacitated

            if engine.state.get("owner_rules_policy") == 1:
                from rpg_vkr.domain.owner_rules_runtime import life

                physical = life(engine, actor)
                if physical.dead or physical.unconscious:
                    continue
            if enabled(engine) and (
                has(engine, actor, "blinded")
                or has(engine, "hero", "invisible")
                or incapacitated(engine, actor)
            ):
                continue
        status = dict(entity.state or {})
        mood = status.get("mood", rules["initial"])
        after = next(
            (t["to"] for t in rules["transitions"] if t["from"] == mood and t["event"] == kind),
            mood,
        )
        relations = dict(status.get("relations", {}))
        hero = dict(relations.get("hero", {}))
        field, amount = ("trust", 1) if kind == "contract_completed" else ("grievance", 3)
        hero[field] = min(10, hero.get(field, 0) + amount)
        relations["hero"] = hero
        status.update(mood=after, relations=relations)
        engine.actors[actor] = replace(entity, state=status)
        engine.events.append(
            {
                "kind": "library_social_transition",
                "version": VERSION,
                "actor": actor,
                "trigger": kind,
                "before": mood,
                "after": after,
                "relation": field,
                "value": hero[field],
            }
        )
    engine._library_social_processed = len(engine.events)
