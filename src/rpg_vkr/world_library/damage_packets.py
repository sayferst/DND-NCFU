"""One hit with multiple damage types causes one canonical HP/death transition."""


def apply(engine, target, components, source):
    if not 1 <= len(components) <= 4 or hasattr(engine, "_library_damage_collector"):
        raise ValueError("Invalid or recursive damage packet")
    for amount, element in components:
        if type(amount) is not int or not 0 <= amount <= 1000000:
            raise ValueError("Invalid component damage")
        from rpg_vkr.world_library.magic_rules import ELEMENTS

        if element not in ELEMENTS:
            raise ValueError("Unknown component element")
    before = engine.hp(target)
    flags = getattr(engine, "owner_hit_flags", {})
    collected = []
    engine._library_damage_collector = collected
    try:
        for amount, element in components:
            engine.damage(target, amount, element, source, False)
    finally:
        del engine._library_damage_collector
        engine.owner_hit_flags = {}
    amount = sum(collected)
    if engine.state.get("owner_rules_policy") == 1:
        from rpg_vkr.domain.owner_rules_runtime import change_hp

        change_hp(engine, target, -amount, **flags)
    else:
        engine.change_hp(target, -amount)
    if amount and source != target and engine.status_power(target, "reflect"):
        # Generic homebrew reflection returns one bounded physical packet.
        engine.damage(
            source, min(amount, engine.status_power(target, "reflect")), "physical", target, False
        )
    if target != "hero" and engine.hp(target) == 0:
        actor, definition = engine.actor(target, alive=False)
        template = definition.properties.get("game_template_id")
        if template and (actor.state or {}).get("encounter_source"):
            from rpg_vkr.domain import game_catalog as content

            spec = content.row(template, "creature")
            if engine.award("defeat:" + template, spec["xp"]):
                for material, quantity in spec["loot"].items():
                    engine.add_item(material, quantity)
    engine.events.append(
        {
            "kind": "library_damage_packet",
            "target": target,
            "source": source,
            "components": [
                {"element": element, "rolled": rolled, "reduced": reduced}
                for (rolled, element), reduced in zip(components, collected, strict=True)
            ],
            "damage": amount,
        }
    )
    return before - engine.hp(target)
