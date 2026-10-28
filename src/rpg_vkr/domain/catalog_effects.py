"""Closed effect vocabulary. Catalog text never becomes executable behavior."""

from rpg_vkr.domain.game_catalog import EFFECTS

STATUS = {
    "burn",
    "slow",
    "weaken",
    "stagger",
    "disarm",
    "bleed",
    "mark",
    "shield",
    "anchor",
    "defence",
    "ranged_guard",
    "resist",
    "clarity",
    "haste",
    "reflect",
    "regenerate",
    "light",
    "perception",
    "craft",
    "accuracy",
    "power",
    "conceal",
}
CURES = {
    "cure_bleed": "bleed",
    "cure_burn": "burn",
    "cure_poison": "poison",
    "cure_weaken": "weaken",
}


def apply(engine, effect, target, record):
    """Apply one already validated effect through the transaction's engine facade."""
    op, power = effect["op"], effect["power"]
    if op not in EFFECTS:
        raise ValueError("Неизвестный обработчик эффекта.")
    if op == "damage":
        attack = engine.roll("1d20", "Магическая атака")
        bonus = engine.hero_bonus(record.get("attack_task", "arcana")) + (
            2 if record["mode"] == "focused" else 0
        )
        if engine.state.get("catalog_revision") == 3:
            task = record.get("attack_task", "arcana")
            bonus += int(
                (task == "ranged" and "marksman" in engine.state["talents"])
                or (task == "melee" and "duelist" in engine.state["talents"])
            )
        defence = engine.defence(target)
        hit = attack == 20 or attack != 1 and attack + bonus >= defence
        amount = engine.roll(record["dice"], "Урон заклинания") if hit else 0
        if attack == 20 and hit:
            amount += engine.roll(record["dice"], "Критический урон")
        if hit and engine.state.get("catalog_revision") == 3:
            from rpg_vkr.domain.character import ability_modifier
            from rpg_vkr.domain.unified import TASKS

            ability = TASKS[record.get("attack_task", "arcana")]
            amount = max(0, amount + ability_modifier(getattr(engine.char, ability)))
        delivered = engine.damage(target, amount, record.get("element", "physical"))
        if engine.state.get("catalog_revision") == 3:
            amount = delivered
        engine.attacks.append(
            {
                "actor_id": "hero",
                "target_id": target,
                "hit": hit,
                "damage": amount,
                "attack_bonus": bonus,
                "total": attack + bonus,
                "defence": defence,
                "defeated": engine.hp(target) == 0,
                "resolver_version": "canonical-effects-2"
                if engine.state.get("catalog_revision") == 3
                else "canonical-effects-1",
            }
        )
        engine.last_damage = amount
        if engine.state.get("catalog_revision") == 3:
            engine.text.append(
                f"Магическая атака: d20({attack}) {bonus:+} против защиты {defence}; урон {amount}."
            )
    elif op in STATUS:
        if (
            target != "hero"
            and target in engine.actors
            and engine.definitions[engine.actors[target].definition_id].kind != "actor"
        ):
            target = "hero"
        engine.status(target, op, power, record["duration"], record.get("element", "physical"))
    elif op in CURES:
        engine.remove_status(target, CURES[op])
    elif op == "heal":
        before = engine.hp(target)
        if engine.state.get("catalog_revision") == 3 and "healer" in engine.state["talents"]:
            power += 1
        engine.change_hp(target, engine.roll(record["dice"], "Исцеление") + power)
        if engine.state.get("catalog_revision") == 3:
            engine.text.append(f"Исцеление: восстановлено {engine.hp(target) - before} HP.")
    elif op == "revive":
        if engine.hp(target) == 0:
            engine.change_hp(target, power)
        else:
            engine.change_hp(target, engine.roll(record["dice"], "Поддержка жизни"))
    elif op == "leech":
        engine.change_hp("hero", min(power * 2, engine.last_damage))
    elif op in ("restore_mp", "restore_st"):
        resource = "mp" if op == "restore_mp" else "st"
        if target == "hero":
            cap = engine.state[resource + "_cap"]
            # A spell never refunds more MP than its own cost; consumables are finite items.
            amount = power if resource == "mp" else power * 2
            if resource == "mp" and record.get("mp", 0):
                amount = min(amount, max(0, record["mp"] - 1))
            engine.state[resource] = min(cap, engine.state[resource] + amount)
        else:
            engine.actor_resource(target, resource, power)
    elif op == "drain_mp":
        removed = engine.actor_resource(target, "mp", -power)
        engine.state["mp"] = min(engine.state["mp_cap"], engine.state["mp"] + max(0, -removed))
    elif op == "repair":
        item = engine.owned(target)
        item["durability"] = min(item.get("durability_cap", 20), item["durability"] + power * 2)
    elif op == "appraise":
        item = engine.owned(target)
        engine.events.append(
            {
                "kind": "appraise",
                "item": target,
                "durability": item["durability"],
                "price_cp": item["price_cp"],
            }
        )
    elif op == "dispel":
        for name in ("burn", "bleed", "slow", "weaken", "stagger", "conceal"):
            engine.remove_status(target, name)
    elif op == "travel":
        destination = record.get("destination") or engine.args.get("destination")
        if target == "hero":
            engine.travel(destination)
        else:
            from rpg_vkr.domain.catalog_world import move_actor

            source = engine.refs[target].place
            if not any(
                p.id == destination
                and (
                    p.parent == source
                    or any(q.id == source and q.parent == destination for q in engine.scene.places)
                )
                for p in engine.scene.places
            ):
                raise ValueError("Нужен известный соседний путь для цели.")
            move_actor(engine, target, destination)
    elif op in ("reveal_items", "reveal_actors", "reveal_nodes", "reveal_routes"):
        if op == "reveal_items":
            values = [t.id for t in engine.scene.things if engine.scene.here(t)]
        elif op == "reveal_actors":
            values = [
                a.id
                for a in engine.scene.actor_refs
                if a.place == engine.scene.current and engine.hp(a.id) > 0
            ]
        elif op == "reveal_nodes":
            values = [
                k
                for k, n in engine.state["living_world"]["nodes"][engine.scene.current].items()
                if n > 0
            ]
        else:
            values = engine.neighbors()
        engine.events.append(
            {"kind": op, "observer": "hero", "place": engine.scene.current, "ids": values}
        )
        engine.state.setdefault("discoveries", {})[op] = values
    else:
        raise ValueError("Эффект не имеет исполнителя: " + op)


def resolve(engine, record, targets):
    for target in targets:
        for index, effect in enumerate(record["effects"]):
            if (
                index
                and engine.state.get("catalog_revision") == 3
                and record["effects"][0]["op"] == "damage"
                and engine.last_damage == 0
            ):
                continue
            apply(engine, effect, target, record)
