"""Playable revision four: one initiative queue, teams and symmetric NPC actions."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain import gameplay as base
from rpg_vkr.domain import gameplay_v2 as v2
from rpg_vkr.domain import gameplay_v3 as v3
from rpg_vkr.domain.catalog import Catalog, seed_catalog
from rpg_vkr.domain.character import Character, ability_modifier
from rpg_vkr.domain.combat import ACTORS, CombatState
from rpg_vkr.domain.d20_combat import Combatant, resolve_attack
from rpg_vkr.domain.d20_progression import D20Progress, level_for_xp
from rpg_vkr.domain.factions import simulate
from rpg_vkr.domain.hero_resources import COSTS, refresh
from rpg_vkr.domain.interactions import InteractiveWorld
from rpg_vkr.domain.resources import reconcile
from rpg_vkr.domain.world import WorldState

VERSION = "gameplay-v3-playable-4"
CATALOG_VERSION = "gameplay-catalog-4"
BATTLE_VERSION = "team-encounter-1"


def initial(identity, character):
    state = v3.initial(identity, character)
    state.update(
        version=VERSION,
        catalog_version=CATALOG_VERSION,
        battle=None,
        last_battle=None,
        npc_resources={},
    )
    return state


def execute(original, command, args, context, dice):
    if original.get("version") != VERSION or original.get("catalog_version") != CATALOG_VERSION:
        raise ValueError("Неизвестная версия группового боя.")
    if not isinstance(command, str) or not isinstance(args, dict):
        raise ValueError("Неверная команда или параметры.")
    attack_spell = (
        command == "cast"
        and args.get("spell") in base.SPELLS
        and (base.SPELLS[args["spell"]][3] == "attack")
    )
    own_command = (
        original["battle"] is not None or command in {"encounter", "attack"} or attack_spell
    )
    if not own_command:
        translated = deepcopy(original)
        translated.update(version=v3.VERSION, catalog_version=v3.CATALOG_VERSION)
        result = v3.execute(translated, command, args, context, dice)
        result["state"].update(version=VERSION, catalog_version=CATALOG_VERSION)
        if result["state"]["minute"] - original["minute"] >= 480:
            for pool in result["state"]["npc_resources"].values():
                pool["st"] = pool["st_cap"]
        return result
    state = deepcopy(original)
    world = WorldState.from_dict(context["world"])
    before_world = world
    combat = CombatState.from_dict(context["combat"])
    catalog = Catalog.from_dict(context["catalog"]) if context["catalog"] else seed_catalog()
    scene = InteractiveWorld.from_dict(context["scene"])
    character = Character.from_dict(context["character"])
    progress = D20Progress.from_dict(context["progress"])
    state, world = refresh(state, world, character, progress.level)
    effective = base.effective_character(state, character)
    if command == "attack" and (
        set(args) != {"target", "lethal"}
        or not isinstance(args.get("target"), str)
        or type(args.get("lethal")) is not int
        or args["lethal"] not in (0, 1)
    ):
        raise ValueError("Нужна цель и явная летальность0/1.")
    if command == "cast" and (
        set(args) != {"spell", "target"}
        or not isinstance(args.get("target"), str)
        or args["spell"] not in state["spells"]
    ):
        raise ValueError("Неверное или неизученное заклинание.")
    if state["st"] < COSTS.get(command, 0):
        raise ValueError("Недостаточно ST; восстановите силы или отступите.")
    if command == "attack" and base.owned(state, state["weapon"])["durability"] <= 0:
        raise ValueError("Оружие сломано.")
    log, events, attacks, rolls = [], [], [], []
    if world.hp <= 0 or combat.active:
        raise ValueError("Групповой бой недоступен после выбытия или в прежнем бою.")

    class TrackedDice:
        def checkpoint(self):
            return dice.checkpoint()

        def restore(self, checkpoint):
            dice.restore(checkpoint)

        def roll_d20(self):
            value = dice.roll_d20()
            rolls.append(asdict(value))
            return value

        def roll(self, expression, *, reason):
            start = dice.checkpoint()[1]
            value = dice.roll(expression, reason=reason)
            rolls.extend(
                {"index": start + i + 1, "value": v} for i, v in enumerate(value.individual_rolls)
            )
            return value

    rng = TrackedDice()

    def definition(id):
        entity = next((e for e in catalog.entities if e.id == id), None)
        model = next(
            (d for d in catalog.definitions if entity and d.id == entity.definition_id), None
        )
        if not entity or not model or model.kind != "actor":
            raise ValueError("Участник не имеет проверенной карточки NPC.")
        return entity, model

    def actor(id):
        if id == "hero":
            return base.hero_combatant(state, world, character, progress)
        entity, model = definition(id)
        props = model.properties
        maximum = props["hp_max"]
        hp = combat.actor(id).hp if id in ACTORS else (entity.state or {}).get("hp", maximum)
        weapon = props.get("weapon", "dagger")
        dex = props.get("dexterity", 10)
        return Combatant(
            id,
            hp,
            maximum,
            dex if weapon in {"longbow", "crossbow"} else props.get("strength", 12),
            dex,
            weapon,
            0,
            props.get("armour", "none"),
            props.get("shield", False),
        )

    def pool(id):
        if id not in state["npc_resources"]:
            cap = definition(id)[1].properties.get("st_max", 20)
            if type(cap) is not int or not 1 <= cap <= 10000:
                raise ValueError("Некорректный максимум ST участника.")
            state["npc_resources"][id] = {"st": cap, "st_cap": cap}
        return state["npc_resources"][id]

    def change_hp(id, hp, *, lethal=False):
        nonlocal world, catalog, combat
        if id == "hero":
            world = replace(world, hp=hp)
            return
        entity, _ = definition(id)
        values = (entity.state or {}) | {"hp": hp}
        if state["battle"]["sides"][id] == "enemy":
            values["disposition"] = "hostile"
        if hp == 0:
            values["life"] = "dead" if lethal else "unconscious"
        catalog = replace(
            catalog,
            entities=tuple(replace(e, state=values) if e.id == id else e for e in catalog.entities),
        )
        if id in ACTORS:
            old = combat.actor(id)
            combat = combat.update(
                replace(old, hp=hp, disposition=values.get("disposition", old.disposition))
            )
        if hp == 0 and state["battle"]["sides"][id] == "enemy" and id not in state["victories"]:
            state["victories"].append(id)
            for ref in scene.actor_refs:
                if ref.id == id or ref.place != scene.current or actor(ref.id).hp <= 0:
                    continue
                if not base.available(state, ref.id, definition(ref.id)[1]):
                    continue
                npc = state["npc"].setdefault(ref.id, {"heard": [], "source": "hero"})
                npc.setdefault("knowledge", []).append(
                    {
                        "event": id,
                        "kind": "personally_known",
                        "source": f"turn_{context['turn']}",
                        "confidence": 100,
                    }
                )

    def distance(first, second):
        positions = state["battle"]["positions"]
        return abs(positions[first] - positions[second])

    def strike(first, second, *, disadvantage=False, lethal=False):
        protected = second == "hero" and any(e["kind"] == "ward" for e in state["effects"])
        outcome = resolve_attack(
            actor(first), actor(second), rng, disadvantage=disadvantage or protected, lethal=lethal
        )
        attacks.append(asdict(outcome))
        change_hp(second, outcome.hp_after, lethal=lethal)
        events.append(
            {
                "kind": "attack",
                "actor": first,
                "target": second,
                "round": state["battle"]["round"],
                "damage": outcome.damage,
            }
        )
        names = {
            "hero": character.name,
            first: definition(first)[1].name if first != "hero" else character.name,
            second: definition(second)[1].name if second != "hero" else character.name,
        }
        log.append(
            f"{names[first]} → {names[second]}: {'попадание' if outcome.hit else 'промах'}, "
            f"урон {outcome.damage}."
        )
        if second == "hero" and protected and outcome.damage and world.hp:
            save = rng.roll_d20().value + ability_modifier(effective.constitution)
            if save < max(10, outcome.damage // 2):
                state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
                log.append("Концентрация потеряна.")

    def finish_if_needed():
        battle = state["battle"]
        won = not any(actor(id).hp > 0 for id in battle["order"] if battle["sides"][id] == "enemy")
        if not won and world.hp > 0:
            return False
        battle["status"] = "won" if won else "hero_unconscious"
        state["last_battle"], state["battle"] = deepcopy(battle), None
        state["active"] = ""
        state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
        log.append("Все противники повержены." if won else "Герой выведен из боя.")
        return True

    def next_slot():
        battle = state["battle"]
        battle["cursor"] = (battle["cursor"] + 1) % len(battle["order"])
        if battle["cursor"] == 0:
            battle["round"] += 1
        state["round"] = battle["round"]

    def automated_until_hero():
        for _ in range(16):
            if finish_if_needed():
                return
            battle = state["battle"]
            id = battle["order"][battle["cursor"]]
            if id == "hero":
                return
            if actor(id).hp:
                targets = [
                    t
                    for t in battle["order"]
                    if battle["sides"][t] != battle["sides"][id] and actor(t).hp
                ]
                target = min(targets, key=lambda t: (distance(id, t), actor(t).hp, t))
                reach = 30 if actor(id).weapon in {"longbow", "crossbow"} else 1
                stamina = pool(id)
                if stamina["st"] < 2:
                    stamina["st"] = min(stamina["st_cap"], stamina["st"] + 3)
                    events.append({"kind": "recover", "actor": id, "round": battle["round"]})
                    log.append(f"{definition(id)[1].name} переводит дух: ST {stamina['st']}.")
                elif distance(id, target) > reach:
                    step = min(6, max(0, distance(id, target) - reach))
                    direction = 1 if battle["positions"][target] > battle["positions"][id] else -1
                    battle["positions"][id] += step * direction
                    stamina["st"] -= 1
                    log.append(f"{definition(id)[1].name} сближается на {step} м.")
                    events.append(
                        {"kind": "move", "actor": id, "round": battle["round"], "metres": step}
                    )
                else:
                    stamina["st"] -= 2
                    strike(
                        id,
                        target,
                        disadvantage=target == "hero" and battle["hero_dodging"],
                        lethal=definition(id)[1].properties.get("lethal_attacks") is True,
                    )
            if finish_if_needed():
                return
            next_slot()
        raise ValueError("Очередь боя не вернулась к ходу героя.")

    if state["battle"] is None:
        if command == "encounter":
            if set(args) != {"enemies", "allies"}:
                raise ValueError("Укажите противников и союзников.")
            enemies, allies = args["enemies"], args["allies"]
        else:
            enemies, allies = [args.get("target")], []
        if (
            not isinstance(enemies, list)
            or not isinstance(allies, list)
            or not enemies
            or not all(isinstance(id, str) for id in enemies + allies)
            or "hero" in enemies + allies
            or len(enemies + allies) > 7
            or len(set(enemies + allies)) != len(enemies + allies)
        ):
            raise ValueError("Нужны от1до7различных NPC без пересечения команд.")
        for id in enemies + allies:
            ref = next(
                (r for r in scene.actor_refs if r.id == id and r.place == scene.current), None
            )
            entity, model = definition(id)
            if not ref or not actor(id).hp or not base.available(state, id, model):
                raise ValueError("Участник отсутствует, недоступен или повержен.")
            if id in allies and (
                model.properties.get("party_ally") is not True
                or (entity.state or {}).get("disposition") != "friendly"
            ):
                raise ValueError("Союзник должен иметь подтверждённое согласие на участие.")
            pool(id)
        totals = {
            id: rng.roll_d20().value + ability_modifier(actor(id).dexterity)
            for id in ["hero", *sorted(enemies + allies)]
        }
        order = sorted(totals, key=lambda id: (-totals[id], id != "hero", id))
        state["battle"] = {
            "version": BATTLE_VERSION,
            "order": order,
            "initiative": totals,
            "cursor": 0,
            "round": 1,
            "hero_dodging": False,
            "place": scene.current,
            "sides": {
                "hero": "party",
                **dict.fromkeys(allies, "party"),
                **dict.fromkeys(enemies, "enemy"),
            },
            "positions": {"hero": 0, **dict.fromkeys(allies, 0), **dict.fromkeys(enemies, 1)},
        }
        state["active"], state["initiative"], state["round"] = (
            enemies[0],
            [totals[id] for id in order],
            1,
        )
        world = replace(world, trading=False)
        for enemy_id in enemies:
            change_hp(enemy_id, actor(enemy_id).hp)
        events.append({"kind": "battle_started", "order": order, "initiative": totals})
        log.append(
            "Начат групповой бой.\nОчередь: "
            + ", ".join(character.name if id == "hero" else definition(id)[1].name for id in order)
            + "."
        )
        automated_until_hero()
    elif command == "encounter":
        raise ValueError("Сначала завершите текущую схватку.")
    if state["battle"] is not None and command not in {"encounter", "advance"}:
        battle = state["battle"]
        expected = {
            "attack": {"target", "lethal"},
            "cast": {"spell", "target"},
            "dodge": set(),
            "recover": set(),
            "move": {"distance"},
            "retreat": set(),
            "bandage": set(),
        }
        if command not in expected or set(args) != expected[command]:
            raise ValueError("Сейчас доступны только действия участника боя.")
        cost = COSTS.get(command, 0)
        if state["st"] < cost:
            raise ValueError("Недостаточно ST; восстановите силы или отступите.")
        battle["hero_dodging"] = False
        if command in {"attack", "cast"}:
            target = args["target"]
            if target != "hero" and (
                target not in battle["sides"]
                or battle["sides"][target] != "enemy"
                or not actor(target).hp
            ):
                raise ValueError("Цель не является действующим противником.")
        if command == "attack":
            if type(args["lethal"]) is not int or args["lethal"] not in (0, 1) or target == "hero":
                raise ValueError("Нужна цель и явная летальность0/1.")
            weapon = base.owned(state, state["weapon"])
            if weapon["durability"] <= 0:
                raise ValueError("Оружие сломано.")
            reach = 30 if actor("hero").weapon in {"longbow", "crossbow"} else 1
            if distance("hero", target) > reach:
                raise ValueError("Цель вне дальности оружия.")
            strike("hero", target, lethal=bool(args["lethal"]))
            weapon["durability"] -= 1
        elif command == "cast":
            key = args["spell"]
            if key not in base.SPELLS or key not in state["spells"]:
                raise ValueError("Сначала изучите заклинание.")
            name, _, mp, effect, expression, reach, components = base.SPELLS[key]
            herbs = [i for i in state["items"] if i["owner"] == "hero" and i["kind"] == "herb"]
            focus = any(
                i["owner"] == "hero" and i["kind"] == "focus" and i["durability"]
                for i in state["items"]
            )
            if state["mp"] < mp or not focus or len(herbs) < components:
                raise ValueError("Нужны MP, исправный фокус и компоненты.")
            if effect != "attack" and target != "hero" or effect == "attack" and target == "hero":
                raise ValueError("Недопустимая цель заклинания.")
            if effect == "attack" and distance("hero", target) > reach:
                raise ValueError("Цель вне дальности заклинания.")
            if effect == "heal" and world.hp == world.max_hp:
                raise ValueError("Здоровье полное.")
            if effect == "ward" and any(e["kind"] == "ward" for e in state["effects"]):
                raise ValueError("Защита уже действует.")
            state["mp"] -= mp
            for herb in herbs[:components]:
                state["items"].remove(herb)
            if effect == "attack":
                dc = 8 + ability_modifier(effective.intelligence) + 2 * progress.rank("arcana")
                save = rng.roll_d20().value + ability_modifier(actor(target).dexterity)
                rolled = rng.roll(expression, reason="Урон заклинания")
                damage = max(0, rolled.total) if save < dc else 0
                change_hp(target, max(0, actor(target).hp - damage))
                events.append(
                    {
                        "kind": "spell",
                        "actor": "hero",
                        "target": target,
                        "damage": damage,
                        "hp_after": actor(target).hp,
                    }
                )
            elif effect == "heal":
                amount = rng.roll(expression, reason="Лечение").total + ability_modifier(
                    effective.intelligence
                )
                amount += 2 if "medic" in state["talents"] else 0
                world = replace(world, hp=min(world.max_hp, world.hp + max(0, amount)))
            else:
                state["effects"].append(
                    {"kind": effect, "expires": state["minute"] + (10 if effect == "ward" else 60)}
                )
            log.append(f"{name}: потрачено {mp} MP.")
        elif command == "bandage":
            if not world.bandages or world.hp == world.max_hp:
                raise ValueError("Нет бинта или здоровье полное.")
            world = replace(world, hp=min(world.max_hp, world.hp + 4), bandages=world.bandages - 1)
        elif command == "dodge":
            battle["hero_dodging"] = True
        elif command == "recover":
            state["st"] = min(state["st_cap"], state["st"] + 3)
        elif command == "move":
            value = args["distance"]
            nearest = min(
                (id for id in battle["order"] if battle["sides"][id] == "enemy" and actor(id).hp),
                key=lambda id: (distance("hero", id), id),
            )
            current = distance("hero", nearest)
            if type(value) is not int or not 1 <= value <= 30 or abs(value - current) > 6:
                raise ValueError("Можно изменить дистанцию на6м, в пределах1–30м.")
            side = -1 if battle["positions"]["hero"] <= battle["positions"][nearest] else 1
            battle["positions"]["hero"] = battle["positions"][nearest] + side * value
            state["distance"] = value
        elif command == "retreat":
            battle["status"] = "retreated"
            state["last_battle"], state["battle"], state["active"] = deepcopy(battle), None, ""
            state["effects"] = [e for e in state["effects"] if e["kind"] != "ward"]
        state["st"] -= cost
        log.append("Действие героя: " + command + ".")
        if state["battle"] is not None and not finish_if_needed():
            next_slot()
            automated_until_hero()
    # Advance time/resources without reusing the duel's response or fictitious artisan counter.
    duration = args.get("minutes") if command == "advance" else 1
    if type(duration) is not int or not 1 <= duration <= 10080:
        raise ValueError("Неверная длительность.")
    scene = reconcile(scene, before_world, world, context["turn"], catalog)
    frozen = set(state["battle"]["order"]) - {"hero"} if state["battle"] else set()
    active, round_number, initiative, distance_value = (
        state["active"],
        state["round"],
        state["initiative"],
        state["distance"],
    )
    translated = deepcopy(state)
    translated.update(version=v2.VERSION, catalog_version=v2.CATALOG_VERSION, active="")
    clock = v2.execute(
        translated,
        "advance",
        {"minutes": duration},
        context
        | {
            "world": asdict(world),
            "combat": combat.to_dict(),
            "catalog": catalog.to_dict(),
            "scene": scene.to_dict(),
        },
        rng,
    )
    after_scene = InteractiveWorld.from_dict(clock["scene"])
    after_scene = replace(
        after_scene,
        actors=tuple(
            next(a for a in scene.actor_refs if a.id == ref.id) if ref.id in frozen else ref
            for ref in after_scene.actor_refs
        ),
    )
    state = clock["state"]
    state.pop("faction_projects", None)
    state.update(
        version=VERSION,
        catalog_version=CATALOG_VERSION,
        active=active,
        round=round_number,
        initiative=initiative,
        distance=distance_value,
    )
    filtered_catalog = replace(
        catalog,
        entities=tuple(
            replace(e, state=(e.state or {}) | {"hp": 0}) if e.id in frozen else e
            for e in catalog.entities
        ),
    )
    state, after_scene, simulation = simulate(state, filtered_catalog, after_scene)
    gained = len(set(state["victories"]) - set(original["victories"])) * 50
    state, world = refresh(
        state, WorldState.from_dict(clock["world"]), character, level_for_xp(progress.xp + gained)
    )
    if state["battle"]:
        enemies = [
            id
            for id in state["battle"]["order"]
            if state["battle"]["sides"][id] == "enemy" and actor(id).hp
        ]
        state["active"] = enemies[0]
        state["distance"] = min(distance("hero", id) for id in enemies)
    else:
        state.update(round=0, distance=1, initiative=[])
    return {
        "state": state,
        "world": asdict(world),
        "combat": combat.to_dict(),
        "catalog": catalog.to_dict(),
        "scene": after_scene.to_dict(),
        "text": "\n".join(log) or "Время мира продвинулось.",
        "rolls": rolls,
        "attacks": attacks,
        "battle_events": events,
        "simulation_events": simulation,
    }
