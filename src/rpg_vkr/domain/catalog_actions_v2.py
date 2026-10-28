"""Player transactions, shared combat rounds and deterministic effect scheduling."""

from copy import deepcopy
from dataclasses import replace

from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog_effects import resolve
from rpg_vkr.domain.character import ABILITY_NAMES, ability_modifier

PARAMETERS = {
    "contract": ({"offer", "operation"}, {"offer", "operation"}),
    "faction": ({"faction", "operation", "amount"}, {"faction", "operation"}),
    "flee": ({"destination"}, {"destination"}),
    "first_aid": ({"target", "item"}, {"target", "item"}),
    "cast": ({"spell", "target", "targets", "item", "destination"}, {"spell"}),
    "ability": ({"talent", "target", "targets", "item", "destination"}, {"talent"}),
    "consume": ({"item", "target", "targets", "destination"}, {"item"}),
    "manufacture": ({"recipe", "result", "quality"}, {"recipe"}),
    "repair": ({"item", "recipe"}, {"item"}),
    "research": ({"entry", "teacher"}, {"entry"}),
    "gather": ({"material", "quantity"}, {"material", "quantity"}),
    "equip": ({"item"}, {"item"}),
    "rest": (set(), set()),
    "wait": ({"minutes"}, {"minutes"}),
    "advance": ({"minutes"}, {"minutes"}),
    "encounter": ({"enemies", "allies"}, {"enemies"}),
    "attack": ({"target", "lethal"}, {"target"}),
    "recover": (set(), set()),
    "dodge": (set(), set()),
    "raise": ({"ability"}, {"ability"}),
    "talent": ({"talent"}, {"talent"}),
    "buy": ({"merchant", "item", "quantity"}, {"merchant", "item"}),
    "sell": ({"merchant", "item", "quantity"}, {"merchant", "item"}),
    "trade_world": (
        {"merchant", "item", "operation", "quantity"},
        {"merchant", "item", "operation"},
    ),
    "check": ({"task", "dc"}, {"task", "dc"}),
    "explore": (set(), set()),
    "travel": ({"destination"}, {"destination"}),
}


def has_tool(e, capability):
    for item in e.state["items"]:
        if item["owner"] != "hero" or item["durability"] <= 0 or item.get("ammunition"):
            continue
        try:
            e.owned(item["id"])
        except ValueError:
            continue
        if e.template(item).get("capability") == capability:
            return True
    return False


def station(e, kind):
    if kind == "tools":
        return has_tool(e, "tools")
    if has_tool(e, kind):
        return True
    for t in e.scene.things:
        if not e.scene.here(t) or t.id not in e.actors:
            continue
        d = e.definitions[e.actors[t.id].definition_id]
        if d.properties.get("station") == kind and (
            d.properties.get("public") or t.owner in ("", "hero", e.scene.current)
        ):
            return True
    return False


def level(e):
    from rpg_vkr.domain.unified import level as calculate

    return calculate(e.state["xp"])


def perform(e, command, args):
    if command not in PARAMETERS or not isinstance(args, dict):
        raise ValueError("Неизвестное действие.")
    allowed, required = PARAMETERS[command]
    if not required <= set(args) <= allowed:
        raise ValueError("Неверные параметры действия.")
    if "lethal" in args and type(args["lethal"]) is not bool:
        raise ValueError("Смертельное намерение задаётся явно.")
    for field in ("targets", "enemies", "allies"):
        if field in args and (
            not isinstance(args[field], list) or any(not isinstance(v, str) for v in args[field])
        ):
            raise ValueError("Неверный список участников.")
    if command in ("flee", "first_aid"):
        from rpg_vkr.domain.field_actions import perform as field_action

        field_action(e, command, args)
        return
    if command in ("contract", "faction"):
        from rpg_vkr.domain.contracts import faction_action
        from rpg_vkr.domain.contracts import perform as contract_action

        (contract_action if command == "contract" else faction_action)(e, args)
        return
    if e.state["battle"] and command in (
        "rest",
        "research",
        "manufacture",
        "repair",
        "gather",
        "buy",
        "sell",
        "trade_world",
        "talent",
        "raise",
        "explore",
        "travel",
    ):
        raise ValueError("Это действие недоступно в схватке.")
    if command in ("cast", "consume", "ability"):
        use(e, command, args)
    elif command in ("manufacture", "repair"):
        craft(e, command, args)
    elif command == "research":
        entry = content.row(args["entry"])
        if entry["kind"] not in ("spell", "recipe") or entry["level"] > level(e):
            raise ValueError("Изучение пока недоступно.")
        if entry["kind"] == "spell" and e.state["mp_cap"] == 0:
            raise ValueError("Класс не использует собственную магию; доступны свитки.")
        field = "spells" if entry["kind"] == "spell" else "known_recipes"
        if entry["id"] in e.state[field]:
            raise ValueError("Это уже изучено.")
        selected = e.require_materials({"mat_2_0": 1, "mat_3_0": 1})
        if args.get("teacher"):
            actor, spec = e.actor(args["teacher"])
            if not any(a.id == actor.id and a.place == e.scene.current for a in e.refs.values()):
                raise ValueError("Учитель далеко.")
            if entry["id"] not in spec.properties.get("teaches", []):
                raise ValueError("Учитель не знает этой техники.")
            fee = 20 * entry["level"]
            if e.state["copper"] < fee:
                raise ValueError("Недостаточно монет.")
            e.state["copper"] -= fee
            e.actors[actor.id] = replace(
                actor,
                state=(actor.state or {})
                | {"gold_cp": (actor.state or {}).get("gold_cp", 0) + fee},
            )
        success = e.check(
            (
                "faith"
                if e.state.get("catalog_revision") == 3
                and e.state["identity"]["class_id"] == "cleric"
                else "arcana"
            )
            if entry["kind"] == "spell"
            else "knowledge",
            5 if args.get("teacher") else 10 + 5 * (entry["level"] // 8),
        )
        for item, n in selected:
            e.consume_item(item, n)
        e.action_minutes = 60
        if success:
            e.state[field].append(entry["id"])
            e.award("learn:" + entry["id"], 10)
        e.text.append(("Изучено: " if success else "Опыт не удался: ") + entry["name"])
    elif command == "gather":
        from rpg_vkr.domain.catalog_engine import RAW

        template = args["material"]
        if template in RAW:
            template = f"mat_{RAW.index(template)}_0"
        row = content.row(template, "material")
        quantity = args["quantity"]
        if row["process"] or type(quantity) is not int or not 1 <= quantity <= 20:
            raise ValueError("Нужно исходное сырьё и количество1–20.")
        if row["base"] not in (1, 2, 3) and not has_tool(e, "tools"):
            raise ValueError("Нужны исправные инструменты.")
        node = e.state["living_world"]["nodes"][e.scene.current]
        deposit = (
            e.state["living_world"]["society"]["places"][e.scene.current]["deposits"]
            if e.state.get("catalog_revision") == 3
            else {}
        )
        opened = max(0, quantity - node.get(template, 0))
        if opened and (deposit.get(template, 0) < opened or not has_tool(e, "tools")):
            raise ValueError("Запас сырья исчерпан.")
        success = e.check("survival", 5 + 5 * (row["base"] // 5))
        e.action_minutes = 10 * quantity
        if success:
            node[template] -= quantity - opened
            if opened:
                from rpg_vkr.domain.society import emit

                deposit[template] -= opened
                emit(
                    e,
                    "deposit_harvested",
                    e.scene.current,
                    actor="hero",
                    resource=template,
                    quantity=opened,
                    deposit_after=deposit[template],
                )
            e.add_item(template, quantity)
            if e.state.get("catalog_revision") == 3:
                gathered = e.state["activity"]["gathered"]
                gathered[template] = gathered.get(template, 0) + quantity
        e.text.append(f"Добыто: {quantity if success else 0} — {row['name']}.")
    elif command in ("wait", "advance"):
        minutes = args["minutes"]
        if type(minutes) is not int or not 0 <= minutes <= 1440:
            raise ValueError("Ожидание0–1440минут.")
        e.action_minutes = minutes
        e.text.append(f"Прошло {minutes} минут.")
    elif command == "rest":
        if any(e.status_power("hero", k) for k in ("burn", "bleed", "poison")):
            raise ValueError("Сначала нужна помощь при активном повреждении.")
        e.world = replace(e.world, hp=e.world.max_hp)
        e.state.update(mp=e.state["mp_cap"], st=e.state["st_cap"])
        e.action_minutes = 480
        e.text.append("Отдых завершён.")
    elif command == "equip":
        item = e.owned(args["item"])
        row = e.template(item)
        slot = (
            "weapon"
            if row["kind"] == "weapon"
            else "shield"
            if row.get("category") == "shield"
            else "armour"
            if row["kind"] == "armour"
            else ""
        )
        if not slot or item["durability"] <= 0:
            raise ValueError("Вещь нельзя экипировать.")
        score = (
            e.char.dexterity
            if row.get("category") in ("dagger", "longbow", "crossbow")
            else e.char.strength
        )
        if score < row.get("requirement", 0) or level(e) < row.get("level", 1):
            raise ValueError("Не выполнены требования снаряжения.")
        if slot == "weapon" and row.get("hands") == 2:
            e.state["shield"] = ""
        if slot == "shield" and e.state["weapon"]:
            if e.template(e.owned(e.state["weapon"])).get("hands") == 2:
                raise ValueError("Оружие двуручное.")
        e.state[slot] = "" if e.state[slot] == item["id"] else item["id"]
        e.text.append("Снаряжение изменено: " + item["name"])
    elif command == "encounter":
        enemies = args["enemies"]
        allies = args.get("allies", [])
        if (
            e.state["battle"]
            or not isinstance(enemies, list)
            or not isinstance(allies, list)
            or not enemies
            or len(enemies + allies) > 7
            or len(set(enemies + allies)) != len(enemies + allies)
        ):
            raise ValueError("Неверный состав схватки.")
        for id in enemies + allies:
            actor, spec = e.actor(id)
            if e.refs[id].place != e.scene.current:
                raise ValueError("Участника нет рядом.")
            if id in allies and (
                not spec.properties.get("party_ally")
                or (actor.state or {}).get("disposition") != "friendly"
            ):
                raise ValueError("Союзник не согласился.")
        initiative = []
        for id in ["hero", *allies, *enemies]:
            dexterity = (
                e.char.dexterity if id == "hero" else e.actor(id)[1].properties.get("dexterity", 10)
            )
            initiative.append(
                (id, e.roll("1d20", "Инициатива: " + id) + ability_modifier(dexterity))
            )
        e.state["battle"] = {
            "order": [id for id, _ in sorted(initiative, key=lambda r: -r[1])],
            "initiative": dict(initiative),
            "sides": {
                "hero": "party",
                **dict.fromkeys(allies, "party"),
                **dict.fromkeys(enemies, "enemy"),
            },
            "round": 1,
        }
        e.state["active"] = enemies[0]
        e.text.append("Началась общая схватка.")
    elif command == "attack":
        if not e.state["battle"] or e.state["battle"]["sides"].get(args["target"]) != "enemy":
            raise ValueError("Нужен противник в активной схватке.")
        hit(e, "hero", args["target"])
        if args.get("lethal") and e.hp(args["target"]) == 0:
            actor, _ = e.actor(args["target"], False)
            e.actors[actor.id] = replace(actor, state=(actor.state or {}) | {"life": "dead"})
    elif command in ("recover", "dodge"):
        if not e.state["battle"]:
            raise ValueError("Нет активной схватки.")
        if command == "recover":
            e.state["st"] = min(e.state["st_cap"], e.state["st"] + 3)
        else:
            if e.state["st"] < 1:
                raise ValueError("Недостаточно ST.")
            e.state["st"] -= 1
            e.status("hero", "defence", 2, 1)
        e.text.append(
            "Герой переводит дух." if command == "recover" else "Герой готовится уклониться."
        )
    elif command == "check":
        from rpg_vkr.domain.unified import DC

        if type(args["dc"]) is not int or args["dc"] not in DC:
            raise ValueError("Неверная сложность.")
        success = e.check(args["task"], args["dc"])
        e.text.append("Успех." if success else "Неудача.")
    elif command in ("raise", "talent"):
        from rpg_vkr.domain.unified import talents

        lv = level(e)
        if command == "raise":
            ability = args["ability"]
            points = 2 * sum(lv >= n for n in (4, 8, 12, 16, 20)) - sum(
                e.state["ability_increases"].values()
            )
            if ability not in ABILITY_NAMES or points <= 0 or getattr(e.char, ability) >= 20:
                raise ValueError("Повышение недоступно.")
            e.state["ability_increases"][ability] = e.state["ability_increases"].get(ability, 0) + 1
            e.char = replace(e.char, **{ability: getattr(e.char, ability) + 1})
        else:
            key = args["talent"]
            choices = 1 + sum(lv >= n for n in (5, 10, 15, 20))
            if key in e.state["talents"] or len(e.state["talents"]) >= choices:
                raise ValueError("Нет свободного выбора таланта.")
            if key not in talents(e.state["identity"]["class_id"]):
                row = content.row(key, "talent")
                if row["class_id"] != e.state["identity"]["class_id"] or row["level"] > lv:
                    raise ValueError("Талант недоступен.")
            e.state["talents"].append(key)
        e.text.append("Развитие героя подтверждено.")
    elif command in ("buy", "sell", "trade_world"):
        trade(e, args.get("operation", command), args)
    elif command == "explore":
        from rpg_vkr.domain.catalog_world import explore

        explore(e)
        e.action_minutes = 30
    elif command == "travel":
        e.travel(args["destination"])
        e.action_minutes = max(5, 30 - 5 * e.status_power("hero", "haste"))


def targets(e, row, args):
    primary = row["effects"][0]["op"]
    if primary in ("repair", "appraise"):
        values = [args.get("item") or args.get("target") or e.state["weapon"]]
        for id in values:
            e.owned(id)
        return values
    values = args.get("targets") or [args.get("target", "hero")]
    if (
        not isinstance(values, list)
        or len(values) != len(set(values))
        or not 1 <= len(values) <= row.get("target_limit", 1)
    ):
        raise ValueError("Неверное число целей.")
    for id in values:
        if id == "hero":
            if primary in ("damage", "drain_mp"):
                raise ValueError("Выберите противника.")
            continue
        e.actor(id, alive=primary != "revive")
        place = e.refs[id].place
        if place != e.scene.current and not (row.get("range", 0) and place in e.neighbors()):
            raise ValueError("Цель вне дальности.")
    return values


def use(e, command, args):
    item = None
    if command == "consume":
        item = e.owned(args["item"])
        row = deepcopy(e.template(item))
        if row["kind"] == "household":
            use_household(e, item, row)
            return
        if row["kind"] != "consumable":
            raise ValueError("Вещь не является расходником.")
        if row["category"] == "ammunition":
            raise ValueError("Боеприпас расходуется при стрельбе.")
        if not row.get("combat", True) and e.state["battle"]:
            raise ValueError("Требуется спокойная обстановка.")
        if row["category"] == "scrolls":
            spell = deepcopy(content.row(item.get("spell_override") or row["spell_id"], "spell"))
            spell["mp"] = 0
            row = spell
        else:
            row.update(mp=0, range=0, target_limit=1, hp_cost=0)
    else:
        key = args["spell"] if command == "cast" else args["talent"]
        row = deepcopy(content.row(key, "spell" if command == "cast" else "talent"))
        if key not in e.state["spells" if command == "cast" else "talents"]:
            raise ValueError("Техника не изучена.")
        if e.state["cooldowns"].get(key, 0) > e.state["minute"]:
            raise ValueError("Способность восстанавливается.")
    if row["level"] > level(e):
        raise ValueError("Недостаточный уровень.")
    if (
        e.state["mp"] < row.get("mp", 0)
        or e.state["st"] < row.get("cost_st", 0)
        or e.world.hp <= row.get("hp_cost", 0)
    ):
        raise ValueError("Недостаточно ресурсов.")
    selected = targets(e, row, args)
    if e.state.get("catalog_revision") == 3:
        from rpg_vkr.domain.catalog_revision3 import pay_ability_materials

        pay_ability_materials(e, row, selected)
    if row["effects"][0]["op"] == "travel":
        row["destination"] = args.get("destination")
        if row["destination"] not in e.neighbors():
            raise ValueError("Нужно выбрать известный соседний путь.")
    if row["effects"][0]["op"] == "revive":
        if any(
            id != "hero" and (e.actor(id, False)[0].state or {}).get("life") == "dead"
            for id in selected
        ):
            raise ValueError("Эта техника возвращает сознание, но не отменяет смерть.")
    if row["effects"][0]["op"] == "heal" and all(
        e.hp(id) == (e.world.max_hp if id == "hero" else e.actor(id, False)[1].properties["hp_max"])
        for id in selected
    ):
        raise ValueError("Здоровье целей полное.")
    e.action_minutes = row.get("minutes", 1)
    e.state["mp"] -= row.get("mp", 0)
    e.state["st"] -= row.get("cost_st", 0)
    e.change_hp("hero", -row.get("hp_cost", 0))
    if command == "ability":
        row["attack_task"] = {
            "warrior": "melee",
            "archer": "ranged",
            "rogue": "stealth",
            "mage": "arcana",
            "cleric": "faith",
            "artisan": "repair",
        }[e.state["identity"]["class_id"]]
        e.state["cooldowns"][row["id"]] = e.state["minute"] + row["cooldown"] * 10
    elif e.state.get("catalog_revision") == 3 and e.state["identity"]["class_id"] == "cleric":
        row["attack_task"] = "faith"
    if item:
        e.consume_item(item)
    if row["effects"][0]["op"] in ("damage", "drain_mp") and not e.state["battle"]:
        e.state["battle"] = {
            "order": ["hero", *selected],
            "sides": {"hero": "party", **dict.fromkeys(selected, "enemy")},
            "round": 1,
        }
        e.state["active"] = selected[0]
    if row["mode"] == "ritual" and e.state["battle"]:
        npc_round(e, "preparation")
        npc_round(e, "preparation")
        if e.world.hp == 0:
            e.text.append("Подготовка прервана: герой выбыл.")
            return
    if row.get("target_limit", 1) > 1:
        count, sides = row["dice"].split("d")
        row["dice"] = f"{max(1, int(count) // 2)}d{sides}"
    if row["mode"] == "delayed":
        e.state["pending"].append(
            {
                "at": e.state["minute"] + e.action_minutes + 1,
                "row": row,
                "targets": selected,
                "remaining": 1,
            }
        )
    else:
        resolve(e, row, selected)
        if row["mode"] == "sustained":
            e.state["pending"].append(
                {
                    "at": e.state["minute"] + e.action_minutes + 10,
                    "row": row,
                    "targets": selected,
                    "remaining": 2,
                }
            )
    e.text.append("Применено: " + row["name"])


def use_household(e, item, row):
    if item["durability"] <= 0:
        raise ValueError("Прибор требует ремонта.")
    capability = row["capability"]
    item["durability"] -= 1
    item["deployed"] = True
    if capability == "light":
        e.status("hero", "light", row["strength"], 6)
        e.status("hero", "perception", row["strength"], 2)
    elif capability == "survey":
        e.state["discoveries"]["resources"] = {
            k: n for k, n in e.state["living_world"]["nodes"][e.scene.current].items() if n > 0
        }
        e.status("hero", "perception", row["strength"], 3)
        e.action_minutes = 10
    elif capability == "camp":
        if e.state["battle"]:
            raise ValueError("Лагерь нельзя разворачивать в схватке.")
        e.status("hero", "regenerate", row["strength"], 3)
        e.action_minutes = 30
    elif capability == "container":
        item["open"] = not item.get("open", True)
    else:
        e.action_minutes = 5
    e.events.append({"kind": "equipment_used", "item": item["id"], "capability": capability})
    e.text.append("Использовано: " + item["name"])


def craft(e, command, args):
    item = e.owned(args["item"]) if command == "repair" else None
    key = args.get("recipe")
    if key is None:
        material = e.template(item).get("material", "mat_0_0")
        base = int(material.split("_")[1])
        key = next(
            (
                r
                for r in e.state["known_recipes"]
                if content.row(r)["category"] == "repair"
                and content.row(r)["compatible_material"] == base
            ),
            "",
        )
    row = content.row(key, "recipe")
    if key not in e.state["known_recipes"] or row["level"] > level(e):
        raise ValueError("Рецепт не изучен.")
    if not has_tool(e, row["tools"]) or not station(e, row["station"]):
        raise ValueError("Нужны инструменты и подходящее рабочее место.")
    quality = args.get("quality", 1)
    if type(quality) is not int or not 1 <= quality <= row["quality_cap"]:
        raise ValueError("Качество недоступно.")
    if command == "repair":
        if row["category"] != "repair" or item["durability"] >= item.get("durability_cap", 20):
            raise ValueError("Этот ремонт не требуется.")
        base = int(e.template(item).get("material", "mat_0_0").split("_")[1])
        if row["compatible_material"] != base:
            raise ValueError("Несовместимая ремонтная деталь.")
    else:
        result = args.get("result") or next(iter(row["outputs"]), None)
        if result not in row["outputs"] or content.row(result)["level"] > level(e):
            raise ValueError("Недоступный результат производства.")
    required = row["ingredients"]
    if command != "repair" and e.state.get("catalog_revision") in (2, 3):
        required = row["materials_by_output"][result]
    ingredients = e.require_materials(required, quality)
    success = e.check(row["task"], row["dc"] + 5 * (quality - 1))
    tool = next(
        (
            i
            for i in e.state["items"]
            if i["owner"] == "hero"
            and e.template(i).get("capability") == "tools"
            and i["durability"] > 0
        ),
        None,
    )
    if tool:
        tool["durability"] -= 1
    for material, n in ingredients:
        e.consume_item(material, n if success else min(1, n))
    e.action_minutes = row["minutes"] * quality
    if success:
        if item:
            item["durability"] = min(
                item["durability_cap"], item["durability"] + row["repair_power"]
            )
        else:
            product = content.row(result)
            made = e.add_item(result, quantity=product.get("batch", 1), made_by="hero")
            made["quality"] = quality
            made["durability_cap"] += 3 * (quality - 1)
            made["durability"] = made["durability_cap"]
            if e.state.get("catalog_revision") == 3:
                stats = e.state["activity"]["crafted"]
                stats[result] = stats.get(result, 0) + product.get("batch", 1)
        e.award("recipe:" + key, 10)
    e.text.append(
        ("Работа выполнена: " if success else "Неудача, часть материалов израсходована: ")
        + row["name"]
    )


def hit(e, attacker, target):
    ammunition = None
    if e.hp(attacker) <= 0 or e.hp(target) <= 0:
        return
    if e.status_power(attacker, "stagger"):
        e.remove_status(attacker, "stagger")
        e.text.append("Оглушение прервало действие.")
        return
    if attacker == "hero":
        item = (
            e.owned(e.state["weapon"])
            if e.state["weapon"] and not e.status_power("hero", "disarm")
            else None
        )
        if item and item["durability"] <= 0:
            raise ValueError("Оружие сломано.")
        row = e.template(item) if item else {"dice": "1d4-1", "category": "unarmed", "stamina": 1}
        task = "ranged" if row["category"] in ("longbow", "crossbow") else "melee"
        if row["category"] == "dagger" and e.char.dexterity > e.char.strength:
            task = "stealth"
        cost = max(
            1,
            row.get("stamina", 2)
            + e.status_power("hero", "slow")
            - e.status_power("hero", "haste"),
        )
        if e.state["st"] < cost:
            raise ValueError("Недостаточно ST.")
        if task == "ranged":
            arrow = next(
                (i for i in e.state["items"] if i.get("ammunition") and i["owner"] == "hero"), None
            )
            if arrow is None:
                raise ValueError("Нет боеприпаса.")
            ammunition = e.template(arrow)
            e.consume_item(arrow)
        e.state["st"] -= cost
        bonus = e.hero_bonus(task) + int(
            ("marksman" if task == "ranged" else "duelist") in e.state["talents"]
        )
        bonus += int(row.get("trait") == "precision")
        damage_bonus = ability_modifier(
            e.char.dexterity if task in ("ranged", "stealth") else e.char.strength
        ) + e.status_power("hero", "power")
        damage_bonus += int(row.get("trait") == "power")
        damage_bonus += sum(r.get("trait") == "power" for _, r in e.worn())
        if row.get("material"):
            material = content.row(row["material"], "material")
            damage_bonus += material["hardness"] // 6
            if task == "ranged":
                bonus += material["elasticity"] // 4
        if item:
            item["durability"] -= 1
    else:
        actor, spec = e.actor(attacker)
        row = {
            "dice": spec.properties.get("damage_dice", "1d4"),
            "category": spec.properties.get("weapon", "dagger"),
        }
        if row["category"] in ("longbow", "crossbow"):
            if (actor.state or {}).get("ammo", 10) > 0:
                e.actor_resource(attacker, "ammo", -1)
            else:
                row.update(category="dagger", dice="1d4")
        if (
            spec.properties.get("behavior") == "caster"
            and (e.actors[attacker].state or {}).get("mp", 10) >= 2
        ):
            e.actor_resource(attacker, "mp", -2)
            row.update(category="focus", damage_type="lightning", dice="1d8")
        bonus = (
            ability_modifier(spec.properties.get("strength", 10))
            + 2
            - e.status_power(attacker, "weaken")
        )
        damage_bonus = ability_modifier(spec.properties.get("strength", 10)) + e.status_power(
            attacker, "power"
        )
        cost = max(1, 1 + e.status_power(attacker, "slow") - e.status_power(attacker, "haste"))
        if (actor.state or {}).get("st", 10) < cost:
            e.actor_resource(attacker, "st", 3)
            return
        e.actor_resource(attacker, "st", -cost)
    defence = e.defence(target) + e.status_power(target, "ranged_guard") * int(
        row["category"] in ("longbow", "crossbow")
    )
    if ammunition and ammunition.get("effect") == "pierce":
        defence -= ammunition["power"]
    value = e.roll("1d20", "Атака")
    bonus += e.status_power(target, "mark")
    success = value == 20 or value != 1 and value + bonus >= defence
    amount = 0
    if success:
        amount = e.roll(row["dice"], "Урон оружия")
        if value == 20:
            amount += e.roll(row["dice"], "Критический урон")
        amount = max(0, amount + damage_bonus)
        delivered = e.damage(target, amount, row.get("damage_type", "physical"), attacker)
        if e.state.get("catalog_revision") == 3:
            amount = delivered
        if ammunition:
            effect = ammunition.get("effect")
            if effect == "power":
                e.damage(target, ammunition["power"], ammunition["element"], attacker)
            elif effect == "drain_mp" and target != "hero":
                e.actor_resource(target, "mp", -ammunition["power"])
            elif effect not in (None, "pierce"):
                e.status(
                    target,
                    "slow" if effect == "net" else effect,
                    ammunition["power"],
                    2,
                    ammunition["element"],
                )
        trait = row.get("trait")
        if (
            trait in ("weaken", "bleed", "slow", "mark")
            and e.hp(target) > 0
            and (e.state.get("catalog_revision") != 3 or amount > 0)
        ):
            e.status(target, trait, 1, 2)
    e.attacks.append(
        {
            "actor_id": attacker,
            "target_id": target,
            "hit": success,
            "damage": amount,
            "attack_bonus": bonus,
            "total": value + bonus,
            "defence": defence,
            "defeated": e.hp(target) == 0,
            "resolver_version": "canonical-effects-2"
            if e.state.get("catalog_revision") == 3
            else "canonical-effects-1",
        }
    )
    name = e.char.name if attacker == "hero" else e.refs[attacker].name
    e.text.append(
        (f"{name}: d20({value}) {bonus:+} против защиты {defence}; урон {amount}.")
        if e.state.get("catalog_revision") == 3
        else f"{attacker}: d20({value}) {bonus:+} против AC{defence}; урон {amount}."
    )


def npc_round(e, command):
    battle = e.state["battle"]
    if not battle:
        return
    order = list(battle["order"])
    hero_index = order.index("hero")
    followers = (
        order[:hero_index]
        if command == "encounter"
        else order[hero_index + 1 :] + order[:hero_index]
    )
    for id in followers:
        if e.world.hp <= 0:
            break
        if e.hp(id) <= 0:
            continue
        actor, spec = e.actor(id)
        enemies = [
            t for t in battle["order"] if battle["sides"][t] != battle["sides"][id] and e.hp(t) > 0
        ]
        if not enemies:
            break
        behavior = spec.properties.get("behavior", "hunter")
        if behavior == "hunter":
            enemies.sort(key=e.hp)
        if behavior == "berserker" and e.hp(id) < spec.properties["hp_max"] // 2:
            e.status(id, "power", 3, 1)
        if (actor.state or {}).get("st", 10) < 2:
            e.actor_resource(id, "st", 3)
            e.events.append({"kind": "npc_recover", "actor": id})
            continue
        if (
            e.hp(id) < spec.properties["hp_max"] // 4
            and behavior in ("skirmisher", "scavenger")
            and e.neighbors()
        ):
            from rpg_vkr.domain.catalog_world import move_actor

            move_actor(e, id, e.neighbors()[0])
            battle["order"].remove(id)
            e.events.append({"kind": "retreat", "actor": id})
            continue
        if behavior == "healer" and (actor.state or {}).get("mp", 10) > 0:
            friends = [
                t
                for t in battle["order"]
                if battle["sides"][t] == battle["sides"][id] and e.hp(t) > 0
            ]
            wounded = min(friends, key=e.hp)
            if e.hp(wounded) < spec.properties["hp_max"] // 2:
                e.actor_resource(id, "mp", -1)
                e.change_hp(wounded, e.roll("1d4", "Лечение NPC"))
                continue
        if behavior == "guardian" and not e.status_power(id, "shield"):
            e.status(id, "shield", 2, 2)
            continue
        if e.refs[id].place != e.scene.current and behavior not in ("archer", "caster"):
            from rpg_vkr.domain.catalog_world import move_actor

            move_actor(e, id, e.scene.current)
            continue
        hit(e, id, enemies[0])
        template = spec.properties.get("game_template_id")
        if (
            template
            and e.attacks
            and e.attacks[-1]["actor_id"] == id
            and e.attacks[-1]["hit"]
            and (e.state.get("catalog_revision") != 3 or e.attacks[-1]["damage"] > 0)
        ):
            skill = content.row(template, "creature")["skill_effect"]
            if skill == "heal":
                e.change_hp(id, 1)
            elif skill == "guard":
                e.status(id, "shield", 1, 2)
            elif skill == "power":
                e.status(id, "power", 1, 2)
            else:
                e.status(enemies[0], skill, 1, 2)
    alive = [id for id in battle["order"] if battle["sides"][id] == "enemy" and e.hp(id) > 0]
    battle["round"] += 1
    if not alive or e.world.hp <= 0:
        e.state.update(last_battle=battle, battle=None, active=None)
    else:
        e.state["active"] = alive[0]


def advance(e, minutes):
    from rpg_vkr.domain.catalog_world import advance_world

    start = e.state["minute"]
    end = start + minutes
    for now in sorted(set([end] + list(range((start // 10 + 1) * 10, end + 1, 10)))):
        e.state["minute"] = now
        for id, rows in e.state["statuses"].items():
            for status in list(rows):
                if status["next"] <= now <= status["until"] and e.hp(id) > 0:
                    if status["op"] in ("burn", "bleed", "poison"):
                        e.damage(id, status["power"], status["element"])
                    elif status["op"] == "regenerate":
                        e.change_hp(id, status["power"])
                    status["next"] = now + 10
            rows[:] = [s for s in rows if s["until"] > now]
        for pending in list(e.state["pending"]):
            if pending["at"] > now:
                continue
            valid = [id for id in pending["targets"] if id in e.actors or id == "hero"]
            if pending["row"]["mode"] == "sustained":
                if e.state["mp"] < 1:
                    valid = []
                else:
                    e.state["mp"] -= 1
            if valid:
                saved = e.action_minutes
                e.action_minutes = 0
                resolve(e, pending["row"], valid)
                e.action_minutes = saved
            pending["remaining"] -= 1
            pending["at"] = now + 10
            if not pending["remaining"] or not valid:
                e.state["pending"].remove(pending)
        advance_world(e, start, now)
        start = now


def trade(e, operation, args):
    merchant, spec = e.actor(args["merchant"])
    if (
        e.refs[merchant.id].place != e.scene.current
        or e.state["living_world"]["residents"][merchant.id]["job"]
        not in ("merchant", "trader", "shopkeeper")
        and not spec.properties.get("can_trade")
    ):
        raise ValueError("Торговец недоступен.")
    quantity = args.get("quantity", 1)
    if type(quantity) is not int or not 1 <= quantity <= (
        20 if e.state.get("catalog_revision") == 3 else 1
    ):
        raise ValueError("Сделки передают одну единицу.")
    wallet = dict(merchant.state or {})
    if wallet.get("closed_until", 0) > e.state["minute"]:
        raise ValueError("Лавка временно закрыта.")
    if operation == "buy":
        entity = e.actors.get(args["item"])
        if entity is None or entity.owner_id != merchant.id:
            raise ValueError("Товара нет у продавца.")
        if entity.quantity < quantity:
            raise ValueError("У продавца нет такого количества.")
        definition = e.definitions[entity.definition_id]
        price = definition.price_cp
        if price is None:
            raise ValueError("Цена не подтверждена.")
        if e.state.get("catalog_revision") == 3:
            from rpg_vkr.domain.society import price_percent, unit_value

            merchandise = next((i for i in e.state["items"] if i["id"] == entity.id), None)
            price = (
                unit_value(e, merchandise, price)
                * price_percent(e, definition.properties.get("game_template_id"))
                // 100
            )
            price = max(1, price)
        else:
            price = max(1, price * e.state["living_world"].get("price_percent", 100) // 100)
        price *= quantity
        if e.state["copper"] < price:
            raise ValueError("Недостаточно денег.")
        thing = e.things[entity.id]
        if entity.quantity > quantity:
            e.actors[entity.id] = replace(entity, quantity=entity.quantity - quantity)
            e.things[entity.id] = replace(thing, quantity=entity.quantity - quantity)
            for existing in e.state["items"]:
                if existing["id"] == entity.id:
                    existing["quantity"] = entity.quantity - quantity
            entity = replace(entity, id=e.mint("purchase"), quantity=quantity)
        entity = replace(entity, owner_id="hero", parent_id="hero")
        e.actors[entity.id] = entity
        e.things[entity.id] = replace(
            thing, id=entity.id, holder="hero", owner="hero", quantity=quantity
        )
        e.state["items"] = [i for i in e.state["items"] if i["id"] != entity.id]
        e.owned(entity.id)
        e.state["copper"] -= price
        wallet["gold_cp"] = wallet.get("gold_cp", 0) + price
    elif operation == "sell":
        item = e.owned(args["item"])
        if item["quantity"] < quantity:
            raise ValueError("Нет такого количества для продажи.")
        if item["id"] in (e.state["weapon"], e.state["armour"], e.state["shield"]):
            raise ValueError("Сначала снимите снаряжение.")
        price = max(1, item["price_cp"] // 2)
        if e.state.get("catalog_revision") == 3:
            from rpg_vkr.domain.society import price_percent, unit_value

            price = max(1, unit_value(e, item) * price_percent(e, item.get("template")) // 200)
        price *= quantity
        if wallet.get("gold_cp", 0) < price:
            raise ValueError("У торговца недостаточно средств.")
        wallet["gold_cp"] -= price
        e.state["copper"] += price
        if item.get("made_by") == "hero":
            e.award("order:" + item["template"], 40 + 10 * e.template(item)["level"])
        if item["quantity"] > quantity:
            e.consume_item(item, quantity)
            sold = dict(item, id=e.mint("sold"), quantity=quantity, owner=merchant.id)
            sold.pop("source", None)
            e.state["items"].append(sold)
        else:
            item["owner"] = merchant.id
            if item.get("source") in e.actors:
                entity = e.actors[item["source"]]
                e.actors[entity.id] = replace(entity, owner_id=merchant.id, parent_id=merchant.id)
                e.things[entity.id] = replace(
                    e.things[entity.id], owner=merchant.id, holder=merchant.id
                )
    else:
        raise ValueError("Неизвестная операция торговли.")
    e.actors[merchant.id] = replace(merchant, state=wallet)
    e.action_minutes = 5
    e.text.append(f"Сделка подтверждена: {price} медных.")
