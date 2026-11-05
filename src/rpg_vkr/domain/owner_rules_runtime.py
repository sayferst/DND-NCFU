"""Versioned owner-rule integration with the canonical saved world, not a second HP store."""

from dataclasses import asdict, replace

from rpg_vkr.domain import owner_rules as rules


def enabled(e):
    return e.state.get("owner_rules_policy") == 1


def life(e, id="hero"):
    hp = e.hp(id)
    maximum = e.world.max_hp if id == "hero" else e.actor(id, False)[1].properties["hp_max"]
    stored = dict(e.state.get("owner_life", {}).get(id, {}))
    stored.pop("hp", None)
    stored.pop("maximum", None)
    if id != "hero":
        actor = e.actor(id, False)[0]
        stored.setdefault("dead", (actor.state or {}).get("life") == "dead")
    if hp > 0:
        stored.update(stable=False, successes=0, failures=0)
    return rules.Life(hp, maximum, **stored)


def apply(e, id, value):
    if id == "hero":
        e.world = replace(e.world, hp=value.hp)
    else:
        actor, _ = e.actor(id, False)
        state = dict(actor.state or {})
        state["hp"] = value.hp
        state["life"] = "dead" if value.dead else "unconscious" if value.unconscious else "alive"
        e.actors[id] = replace(actor, state=state)
    metadata = asdict(value)
    metadata.pop("hp")
    metadata.pop("maximum")
    e.state.setdefault("owner_life", {})[id] = metadata
    recoveries = e.state.setdefault("owner_recovery", {})
    if value.stable and id not in recoveries:
        recoveries[id] = e.state["minute"] + 60 * rule_roll(
            e, "1d4", "Срок естественного восстановления", id
        )
    elif not value.stable:
        recoveries.pop(id, None)
    return value


def change_hp(e, id, delta, *, critical=False, nonlethal=False):
    if id == "hero" and delta < 0:
        e.owner_rest_interrupted = True
    old = life(e, id)
    value = (
        rules.heal(old, delta)
        if delta >= 0
        else rules.damage(old, -delta, critical=critical, nonlethal=nonlethal)
    )
    apply(e, id, value)
    if value != old and public_actor(e, id):
        e.events.append(
            {"kind": "owner_life", "actor": id, "before": old.public(), "after": value.public()}
        )
    return value.hp


def finish_rest(e):
    if not getattr(e, "owner_rest_pending", False):
        return
    value = life(e)
    if getattr(e, "owner_rest_interrupted", False) or value.unconscious or value.dead:
        e.text.append("Отдых прерван повреждением: восстановления и снятия истощения нет.")
        e.events.append({"kind": "owner_rest", "completed": False})
        return
    apply(e, "hero", rules.long_rest(value))
    e.state.update(mp=e.state["mp_cap"], st=e.state["st_cap"])
    e.state["owner_last_rest_end"] = e.state["minute"]
    e.events.append({"kind": "owner_rest", "completed": True, "after": life(e).public()})
    e.text.append(
        "Длительный отдых завершён; HP, MP и ST восстановлены, истощение уменьшено до "
        + str(life(e).exhaustion)
        + "."
    )


def resolve_check(e, natural, modifier, task, dc, *, partial=False):
    result = rules.check(natural, modifier, dc, exhaustion=life(e).exhaustion, partial=partial)
    e.events.append({"kind": "owner_check", "task": task, **result})
    if result["complication"]:
        e.owner_complication_minutes = getattr(e, "owner_complication_minutes", 0) + 1
        e.events.append({"kind": "owner_complication", "consequence": "lost_tempo", "minutes": 1})
        e.text.append("Натуральная1: потеря темпа добавляет минуту к действию.")
    return result


def save(e, id):
    before = life(e, id)
    if before.dead or before.hp or before.stable:
        raise ValueError("Спасбросок смерти сейчас не требуется.")
    natural = rule_roll(e, "1d20", "Спасбросок смерти", id)
    e.owner_saved_this_action = getattr(e, "owner_saved_this_action", set()) | {id}
    after = apply(e, id, rules.death_save(before, natural))
    if public_actor(e, id):
        e.events.append(
            {
                "kind": "owner_death_save",
                "actor": id,
                "natural": natural,
                "total": natural - 2 * before.exhaustion,
                "before": before.public(),
                "after": after.public(),
            }
        )
        e.text.append(
            "Спасбросок смерти: "
            + (
                "смерть."
                if after.dead
                else "сознание возвращается."
                if after.hp
                else "стабилизация."
                if after.stable
                else "исход ещё не решён."
            )
        )
    return after


def perform(e, command, args):
    if not enabled(e):
        return False
    if command == "food_terms":
        if args:
            raise ValueError("Уточнение условий не принимает скрытые поправки.")
        from rpg_vkr.domain.food_negotiation import disclose_terms

        disclose_terms(e)
    elif command == "death_save":
        if args:
            raise ValueError("Спасбросок смерти героя не принимает дополнительные параметры.")
        save(e, "hero")
    elif command == "stabilize":
        if not isinstance(args, dict) or set(args) != {"target"}:
            raise ValueError("Назовите цель первой помощи.")
        target = args["target"]
        actor, _ = e.actor(target, False)
        if e.refs[target].place != e.scene.current:
            raise ValueError("Цель помощи далеко.")
        before = life(e, target)
        rules.stabilize(before)  # Validate eligibility before a roll or any cost.
        if e.check("medicine", 10):
            apply(e, target, rules.stabilize(before))
            e.text.append("Цель стабильна при0HP и остаётся без сознания.")
        else:
            e.text.append("Стабилизировать цель пока не удалось.")
        e.events.append(
            {"kind": "owner_stabilization", "actor": target, "after": life(e, target).public()}
        )
    elif command == "overcast":
        if not isinstance(args, dict) or not {"spell", "payment"} <= set(args) <= {
            "spell",
            "payment",
            "target",
            "targets",
            "item",
            "destination",
        }:
            raise ValueError("Укажите известное заклинание и явный способ перерасхода.")
        from rpg_vkr.domain.catalog_actions_v2 import use

        use(e, "cast", args)
    else:
        return False
    return True


def public_actor(e, id):
    return id == "hero" or (id in e.refs and e.refs[id].place == e.scene.current)


def rule_roll(e, expression, reason, id):
    # Unobserved world rolls remain deterministic without disclosing distant NPCs
    # to the public narrator receipt.
    return (
        e.roll(expression, reason)
        if public_actor(e, id)
        else e.dice.roll(expression, reason=reason).total
    )


def recover_and_resolve(e, start, end):
    """Resolve elapsed rule turns and stable recovery, retaining the canonical RNG."""
    for id, at in list(e.state.get("owner_recovery", {}).items()):
        value = life(e, id)
        if at <= end and value.stable and not value.dead and value.hp == 0:
            change_hp(e, id, 1)
            if public_actor(e, id):
                e.text.append("Стабильный пострадавший естественно восстановил1HP.")
    if e.state.get("battle"):
        return  # Battle turns perform their own saves, exactly once per turn.
    saved = getattr(e, "owner_saved_this_action", set())
    for id, actor in list(e.actors.items()):
        if e.definitions[actor.definition_id].kind != "actor" or e.hp(id) > 0 or id in saved:
            continue
        value = life(e, id)
        if value.dead or value.stable:
            continue
        for _ in range(min(5, max(0, end - start))):
            value = save(e, id)
            if value.dead or value.stable or value.hp:
                break


def assist_fallen(e, id, definition, battle):
    """A declared healer spends its turn helping a living downed ally, never a corpse."""
    if definition.properties.get("behavior") != "healer" and not definition.properties.get(
        "stabilizes_allies"
    ):
        return False
    if e.refs[id].place != e.scene.current:
        return False
    friends = [
        target
        for target in battle["order"]
        if target != id
        and battle["sides"][target] == battle["sides"][id]
        and e.hp(target) == 0
        and not life(e, target).dead
        and (target == "hero" or e.refs[target].place == e.scene.current)
    ]
    if not friends:
        return False
    target = next((target for target in friends if not life(e, target).stable), friends[0])
    actor, _ = e.actor(id)
    if definition.properties.get("behavior") == "healer" and (actor.state or {}).get("mp", 10) > 0:
        e.actor_resource(id, "mp", -1)
        change_hp(e, target, rule_roll(e, "1d4", "Лечение союзника", id))
        e.events.append(
            {
                "kind": "owner_ally_heal",
                "actor": id,
                "target": target,
                "after": life(e, target).public(),
            }
        )
        return True
    if life(e, target).stable:
        return False
    from rpg_vkr.domain.character import ability_modifier

    natural = rule_roll(e, "1d20", "Первая помощь союзника", id)
    result = rules.check(
        natural,
        ability_modifier(definition.properties.get("wisdom", 10)) + 2,
        10,
        exhaustion=life(e, id).exhaustion,
        partial=False,
    )
    if result["succeeded"]:
        apply(e, target, rules.stabilize(life(e, target)))
    if result["complication"]:
        e.owner_complication_minutes = getattr(e, "owner_complication_minutes", 0) + 1
    e.events.append({"kind": "owner_ally_stabilize", "actor": id, "target": target, **result})
    return True
