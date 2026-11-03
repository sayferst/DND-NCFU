"""Composable physical plans. Declarative affordances, not scenario handlers.

The language model can select primitives and real IDs; material facts, costs,
DC, quality and outcomes are exclusively derived here. No model-authored stats.
"""

import re
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256

from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog import Definition
from rpg_vkr.domain.character import ability_modifier


@dataclass(frozen=True)
class Form:
    name: str
    requires: tuple[str, ...]
    tools: tuple[str, ...]
    kind: str = "tool"
    category: str = "miscellaneous"
    dice: str = ""


# A small vocabulary of mechanics. New combinations use the same resolver.
FORMS = {
    "fishing_gear": Form("Импровизированная удочка", ("shaft", "cord"), ("cut",)),
    "spear": Form("Самодельное копьё", ("shaft",), ("cut",), "weapon", "spear", "1d4"),
    "splint": Form("Самодельная шина", ("shaft", "binding"), ("cut",)),
    "sling": Form("Самодельная перевязь", ("fabric",), ("cut",)),
    "wrap": Form("Защитная обмотка", ("fabric",), ("cut",)),
    "tie": Form("Импровизированная связка", ("cord",), ()),
}
GOAL_WORDS = {
    "fishing_gear": r"удоч|рыболовн\w* снаст",
    "spear": r"копь",
    "splint": r"шин[ауые]|шину",
    "sling": r"перевязь|перевяз[ьи]",
    "wrap": r"обмот",
    "tie": r"связк",
}
OPERATIONS = {"transform", "repair", "restore", "use", "magic", "take", "move", "explore"}
AFFORDANCES = {"flight", "currency", "catch_fish", "support", "cut", "bind", "protect"}
MATERIAL_TRAITS = {
    0: {"metal", "rigid"},
    1: {"wood", "shaft", "rigid"},
    2: {"plant"},
    3: {"fabric", "binding"},
    4: {"fabric", "binding"},
    5: {"stone", "rigid"},
    6: {"metal", "rigid"},
}
CATEGORY_TRAITS = {
    "longbow": {"shaft", "cord", "binding", "wood", "rigid"},
    "crossbow": {"shaft", "cord", "binding", "wood", "rigid"},
    "dagger": {"cut", "point", "metal"},
    "sword": {"cut", "metal"},
    "axe": {"cut", "shaft", "metal"},
    "spear": {"point", "shaft"},
}


def clarify(message):
    raise ValueError("CLARIFICATION_REQUIRED: " + message)


def one(rows, message):
    if len(rows) != 1:
        clarify(message)
    return rows[0]


def traits(e, item):
    row = e.template(item)
    result = set(CATEGORY_TRAITS.get(row.get("category"), ()))
    if row.get("capability") == "tools":
        result |= {"cut", "repair"}
    if row.get("kind") == "armour":
        result.add("protect")
    material = row.get("material")
    if row.get("kind") == "material":
        material = row["id"]
    if material and material.startswith("mat_"):
        result |= MATERIAL_TRAITS.get(int(material.split("_")[1]), set())
    if item.get("source") in e.actors:
        definition = e.definitions[e.actors[item["source"]].definition_id]
        # Explicit world facts, never properties inferred from the item's name.
        raw = definition.properties.get("affordances", [])
        if isinstance(raw, list):
            allowed = set.union(*MATERIAL_TRAITS.values(), *CATEGORY_TRAITS.values()) | AFFORDANCES
            result |= {t for t in raw if isinstance(t, str) and t in allowed}
    result |= set(item.get("affordances", []))
    return result


def possessions(e):
    result = []
    for id in sorted({i["id"] for i in e.state["items"]} | {t.id for t in e.scene.carried()}):
        try:
            result.append(e.owned(id))
        except ValueError:
            pass
    return result


def mentions(text, rows, name=lambda r: r["name"]):
    words = re.findall(r"[а-яa-z_]+", text.casefold().replace("ё", "е"))
    return [
        r
        for r in rows
        if any(
            len(a) >= 3
            and len(b) >= 3
            and a[: min(4, len(a), len(b))] == b[: min(4, len(a), len(b))]
            for a in words
            for b in re.findall(r"[а-яa-z_]+", name(r).casefold().replace("ё", "е"))
        )
    ]


def infer_plan(e, intent):
    """Conservative offline binding; the model can supply the identical closed schema."""
    owned = possessions(e)
    sources = mentions(intent.text, owned)
    operation, goal, tool = intent.kind, "", ""
    if operation == "transform":
        goals = [
            key for key, pattern in GOAL_WORDS.items() if re.search(pattern, intent.text.casefold())
        ]
        goal = one(goals, "Уточните назначение изделия в пределах поддерживаемых свойств.")
        # A tool named as an input needs explicit disambiguation. No dual-use copy.
        tools = [i for i in owned if i["durability"] > 0 and "cut" in traits(e, i)]
        required = FORMS[goal].tools
        tool = tools[0]["id"] if tools and required else ""
        sources = [i for i in sources if i["id"] != tool]
        if not sources:
            clarify("Назовите реальные исходные материалы или предметы.")
    elif operation in ("repair", "restore"):
        sources = sources or [i for i in owned if i.get("craft_origin")]
        tools = [i for i in owned if i["durability"] > 0 and "repair" in traits(e, i)]
        tool = tools[0]["id"] if tools else ""
    elif operation in ("magic", "use"):
        value = intent.text.casefold()
        goals = [
            key
            for key, pattern in {
                "flight": r"взлет|летать|полет|в воздух",
                "currency": r"монет|золот",
                "catch_fish": r"рыбач|рыбу",
                "support": r"опор|подпер|подпир|поддерж",
                "cut": r"разрез|отрез",
                "bind": r"связ|привяз",
                "protect": r"укры|защит",
            }.items()
            if re.search(pattern, value)
        ]
        goal = one(goals, "Уточните одно назначение использования предмета.")
        # Source IDs, when present in the text, must actually exist.
        if operation == "use" and not sources:
            clarify("Укажите существующий доступный предмет.")
    elif operation == "take":
        sources = mentions(
            intent.text, [t for t in e.scene.things if e.scene.here(t)], name=lambda t: t.name
        )
        sources = [one(sources, "Назовите один существующий предмет рядом с героем.")]
    elif operation == "move":
        goals = mentions(
            intent.text, [p for p in e.scene.places if p.id in e.neighbors()], name=lambda p: p.name
        )
        goal = one(goals, "Укажите один известный соседний путь или место назначения.").id
    return {
        "operation": operation,
        "goal": goal,
        "items": [r.id if hasattr(r, "id") else r["id"] for r in sources],
        "tool": tool,
    }


def validate_plan(plan):
    from rpg_vkr.domain.interactions import identifier

    if not isinstance(plan, dict) or set(plan) != {"operation", "goal", "items", "tool"}:
        raise ValueError("Expected a closed attempt plan")
    if (
        not isinstance(plan["operation"], str)
        or plan["operation"] not in OPERATIONS
        or not isinstance(plan["goal"], str)
        or len(plan["goal"]) > 64
    ):
        raise ValueError("Unsupported attempt primitive")
    if (
        not isinstance(plan["items"], list)
        or len(plan["items"]) > 6
        or any(not isinstance(i, str) for i in plan["items"])
        or len(set(plan["items"])) != len(plan["items"])
        or not isinstance(plan["tool"], str)
    ):
        raise ValueError("Invalid physical inputs")
    if plan["tool"] in plan["items"]:
        raise ValueError("A consumed input cannot simultaneously be a retained tool")
    for id in plan["items"] + ([plan["tool"]] if plan["tool"] else []):
        identifier(id)
    return plan


def physical(e, item, *, name, kind, capabilities, durability, penalty, form=""):
    source = item.get("source", item["id"])
    if item.get("quantity", 1) != 1:
        clarify("Сначала отделите один исходный предмет от стопки.")
    item.setdefault(
        "craft_origin",
        {
            "template": item.get("template"),
            "kind": item["kind"],
            "name": item["name"],
            "durability": item["durability"],
            "durability_cap": item["durability_cap"],
            "definition_id": e.actors[source].definition_id,
        },
    )
    item.pop("template", None)
    item.update(
        kind=kind,
        name=name,
        durability=durability,
        durability_cap=max(1, durability),
        price_cp=0,
        affordances=list(capabilities),
        usage_penalty=penalty,
        form=form,
    )
    for slot in ("weapon", "armour", "shield"):
        if e.state[slot] == item["id"]:
            e.state[slot] = ""
    definition_id = "improvised_" + sha256(source.encode()).hexdigest()[:24]
    e.definitions[definition_id] = Definition(
        definition_id,
        name,
        "item",
        ("miscellaneous",),
        {"portable": True, "durability": max(1, durability), "affordances": list(capabilities)},
        price_cp=0,
        origin="project-homebrew",
    )
    e.actors[source] = replace(
        e.actors[source],
        definition_id=definition_id,
        state=(e.actors[source].state or {}) | {"condition": durability},
    )
    e.things[source] = replace(e.things[source], name=name)


def transform(e, plan):
    form = FORMS.get(plan["goal"])
    if form is None:
        clarify("Форма изделия не поддержана; новый эффект не создаётся из описания.")
    items = [e.owned(id) for id in plan["items"]]
    if not items or any(i["durability"] <= 0 for i in items):
        clarify("Нужны доступные пригодные исходные предметы.")
    capabilities = set().union(*(traits(e, i) for i in items))
    tool = e.owned(plan["tool"]) if plan["tool"] else None
    if form.tools and (
        not tool or tool["durability"] <= 0 or not set(form.tools) <= traits(e, tool)
    ):
        clarify("Нужен реально доступный инструмент с необходимыми свойствами.")
    if not set(form.requires) <= capabilities:
        e.text.append(
            "Попытку можно начать, но материалам недостаёт необходимых свойств: "
            + ", ".join(sorted(set(form.requires) - capabilities))
            + ". Бросок не создаёт их."
        )
        return "ATTEMPT_WITHOUT_TARGET_SUCCESS", "target_unreachable", None, None
    if any(i.get("quantity", 1) != 1 for i in items):
        clarify("Для сборки укажите отдельные физические единицы.")
    e.action_minutes = 30
    natural = e.roll("1d20", "Работа с материалами: Ловкость")
    modifier = ability_modifier(e.char.dexterity) - e.status_power("hero", "weaken")
    total, dc = natural + modifier, 20
    target = items[0]
    outcome = (
        "damaged"
        if total <= 10
        else "partial"
        if total <= 17
        else "rough_success"
        if total <= 20
        else "success"
    )
    # One resulting ID retains provenance of every consumed source.
    origins = [
        {
            k: deepcopy(i[k])
            for k in ("id", "source", "template", "form", "quantity", "durability")
            if k in i
        }
        for i in items
    ]
    for other in items[1:]:
        e.consume_item(other)
    if outcome == "damaged":
        physical(
            e,
            target,
            name="Повреждённые материалы",
            kind="damaged_materials",
            capabilities=(),
            durability=0,
            penalty=-3,
        )
        e.status("hero", "weaken", 1, 3)
    elif outcome == "partial":
        physical(
            e,
            target,
            name="Незавершённая заготовка",
            kind="salvage",
            capabilities=(),
            durability=2,
            penalty=-3,
        )
    else:
        rough = outcome == "rough_success"
        physical(
            e,
            target,
            name=form.name,
            kind=form.kind,
            capabilities=form.requires,
            durability=3 if rough else 6,
            penalty=-3 if rough else -1,
            form=plan["goal"],
        )
    target["consumed_provenance"] = origins
    if tool:
        tool["durability"] = max(0, tool["durability"] - 1)
    e.text.append(f"{form.name}: {outcome}. d20({natural}) {modifier:+} = {total}.")
    e.text.append(
        "Исходные предметы больше не доступны отдельно; свойства результата ограничены материалами."
    )
    return "CHECK_REQUIRED", outcome, dc, total


def repair(e, plan):
    target = one([e.owned(id) for id in plan["items"]], "Укажите один ремонтируемый предмет.")
    tool = e.owned(plan["tool"]) if plan["tool"] else None
    if not tool or tool["durability"] <= 0 or "repair" not in traits(e, tool):
        clarify("Нужен пригодный ремонтный инструмент.")
    origin = target.get("craft_origin") if plan["operation"] == "restore" else None
    if plan["operation"] == "restore" and (not origin or not origin.get("template")):
        clarify("Сохранённый исходный предмет для обратной сборки не найден.")
    if not origin and target["durability"] >= target["durability_cap"]:
        clarify("Предмет исправен; ремонт пока не требуется.")
    category = traits(e, target)
    material = (
        "mat_1_0"
        if origin or "wood" in category
        else "mat_3_0"
        if "fabric" in category
        else "mat_0_0"
    )
    selected = e.require_materials({material: 1})
    e.action_minutes = 30
    natural = e.roll("1d20", "Ремонт")
    total = natural + e.hero_bonus("repair")
    for item, quantity in selected:
        e.consume_item(item, quantity)
    tool["durability"] -= 1
    if total >= 15:
        if origin:
            target.update(
                template=origin["template"],
                name=origin["name"],
                durability=max(1, origin["durability"] // 2),
                durability_cap=origin["durability_cap"],
                kind=origin["kind"],
            )
            target.pop("craft_origin", None)
            target.pop("form", None)
            target.pop("affordances", None)
            source = target.get("source", target["id"])
            e.actors[source] = replace(e.actors[source], definition_id=origin["definition_id"])
        else:
            target["durability"] = min(target["durability_cap"], target["durability"] + 5)
        outcome = "success"
    elif total >= 10 and not origin:
        target["durability"] = min(target["durability_cap"], target["durability"] + 2)
        outcome = "partial"
    else:
        outcome = "failed"
    e.text.append(f"Ремонт: {outcome}; итог {total}, DC15. Материал и время израсходованы.")
    return "CHECK_REQUIRED", outcome, 15, total


def use(e, plan):
    items = [e.owned(id) for id in plan["items"]]
    if any(i["durability"] <= 0 for i in items):
        clarify("Выбранный предмет повреждён; уточните способ попытки.")
    capabilities = set().union(*(traits(e, i) for i in items))
    goal = plan["goal"]
    if goal not in AFFORDANCES:
        clarify("Запрошенный эффект не входит в поддерживаемые механики.")
    needed = {"support": "rigid", "bind": "binding", "protect": "fabric"}.get(goal, goal)
    if plan["operation"] == "magic":
        # Only an actual, implemented effect in a learned spell can grant an ability.
        spells = [content.row(k) for k in e.state["spells"] if k in content.load()]
        candidates = [s for s in spells if any(x["op"] == goal for x in s.get("effects", []))]
        if candidates:
            from rpg_vkr.domain.catalog_actions_v2 import perform

            spell = one(candidates, "Укажите конкретную изученную способность.")
            perform(e, "cast", {"spell": spell["id"], "target": "hero"})
            return "AUTO_SUCCESS", "effect_applied", None, None
    elif needed in capabilities and goal not in ("flight", "currency", "catch_fish"):
        for item in items:
            item["deployed"] = {"affordance": goal, "place": e.scene.current}
            source = item.get("source", item["id"])
            if source not in e.actors or source not in e.things:
                clarify("Нужно зарегистрированное физическое размещение предмета.")
            e.actors[source] = replace(e.actors[source], parent_id=e.scene.current)
            e.things[source] = replace(e.things[source], holder=e.scene.current)
        e.state.setdefault("physical_uses", []).append(
            {
                "items": plan["items"],
                "affordance": goal,
                "place": e.scene.current,
                "minute": e.state["minute"],
            }
        )
        e.text.append(
            "Предмет размещён для выбранной цели с подтверждённым свойством: "
            + goal
            + ". Иные эффекты пока не подтверждены."
        )
        return "AUTO_SUCCESS", "object_deployed", None, None
    e.text.append(
        "Попытка выполнена в доступных физических пределах. Запрошенный результат "
        "не возникает: необходимые свойства или исполняемая способность не подтверждены."
    )
    return "ATTEMPT_WITHOUT_TARGET_SUCCESS", "target_unreachable", None, None


def take(e, plan):
    id = one(plan["items"], "Укажите один предмет.")
    thing = one(
        [t for t in e.scene.things if t.id == id and e.scene.here(t)],
        "Предмет должен находиться рядом.",
    )
    entity = e.actors.get(id)
    definition = e.definitions.get(entity.definition_id) if entity else None
    if not definition or definition.properties.get("portable") is not True:
        clarify("Переносимость предмета пока не подтверждена.")
    if thing.owner not in ("", "hero", e.scene.current):
        clarify("У вещи есть владелец; уточните передачу или отдельную попытку кражи.")
    # Root visibility does not open a closed nested container.
    cursor = thing
    while cursor.holder in e.things:
        parent = e.things[cursor.holder]
        parent_entity = e.actors.get(parent.id)
        if parent_entity and (parent_entity.state or {}).get("open") is False:
            clarify("Сначала откройте контейнер.")
        cursor = parent
    e.actors[id] = replace(entity, owner_id="hero", parent_id="hero")
    e.things[id] = replace(thing, owner="hero", holder="hero")
    e.scene = replace(e.scene, things=tuple(e.things.values()))
    e.owned(id).pop("deployed", None)
    e.text.append("Подобран существующий предмет: " + thing.name + ".")
    return "AUTO_SUCCESS", "completed", None, None


def move(e, plan):
    from rpg_vkr.domain.catalog_actions_v2 import perform

    if plan["operation"] == "explore":
        perform(e, "explore", {})
        return "CHECK_REQUIRED", "explored", None, None
    perform(e, "travel", {"destination": plan["goal"]})
    e.text.append("Герой прошёл по существующему пути: " + e.scene.place().name + ".")
    return "AUTO_SUCCESS", "completed", None, None


RESOLVERS = {
    "transform": transform,
    "repair": repair,
    "restore": repair,
    "use": use,
    "magic": use,
    "take": take,
    "move": move,
    "explore": move,
}


def public_facts(session):
    """Only accessible hero items; never expose hidden NPC wallets or remote stocks."""
    from rpg_vkr.domain.catalog_engine import Engine
    from rpg_vkr.domain.dice import DiceRoller
    from rpg_vkr.unified_session import context

    dice = DiceRoller(session.dice.seed)
    dice.restore(session.dice.checkpoint())
    engine = Engine(session.gameplay, context(session), dice, {})
    return [
        {
            "id": i["id"],
            "name": i["name"],
            "condition": i["durability"],
            "affordances": sorted(traits(engine, i)),
            "quantity": i.get("quantity", 1),
        }
        for i in possessions(engine)[:40]
    ]


def resolve(e, plan):
    validate_plan(plan)
    if e.state.get("free_action_policy") != 1:
        raise ValueError("Свободные планы не включены для этой кампании.")
    if e.state["battle"]:
        clarify("В схватке укажите отдельное боевое действие.")
    before = deepcopy(e.state["items"])
    roll_start = len(e.rolls)
    mode, outcome, dc, total = RESOLVERS[plan["operation"]](e, plan)
    old = {i["id"]: i for i in before}
    new = {i["id"]: i for i in e.state["items"]}
    record = {
        "version": 1,
        "plan": deepcopy(plan),
        "mode": mode,
        "outcome": outcome,
        "dc": dc,
        "total": total,
        "duration_minutes": e.action_minutes,
        "item_changes": [
            {"id": id, "before": old.get(id), "after": deepcopy(new.get(id))}
            for id in sorted(old.keys() | new.keys())
            if old.get(id) != new.get(id)
        ],
        "mechanics": "physical-affordances-1",
        "dice": deepcopy(e.rolls[roll_start:]),
    }
    e.state.setdefault("free_action_log", []).append(record)
    e.events.append({"kind": "free_attempt", **deepcopy(record)})
    return record
