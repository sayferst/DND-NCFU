"""Closed AI action proposals; only Session commits resource changes."""

from rpg_vkr.domain import game_catalog as catalog
from rpg_vkr.domain.attempt_plans import FORMS, public_facts, validate_plan
from rpg_vkr.domain.catalog_actions_v2 import PARAMETERS
from rpg_vkr.domain.contracts import public as public_contracts
from rpg_vkr.domain.unified import level

# Development/state management commands are never part of the model protocol.
COMMANDS = set(PARAMETERS) - {"advance", "check", "raise", "talent", "trade_world"}
OWNER_PARAMETERS = {
    "death_save": (set(), set()),
    "stabilize": ({"target"}, {"target"}),
    "food_terms": (set(), set()),
    "overcast": (
        {"spell", "payment", "target", "targets", "item", "destination"},
        {"spell", "payment"},
    ),
}


def validate_proposal(value, plan, state):
    if (
        not state.get("catalog_actions")
        or not isinstance(value, dict)
        or set(value) != {"command", "args"}
    ):
        raise ValueError("Заявка единой механики недоступна.")
    command, args = value["command"], value["args"]
    actions = state["catalog_actions"] if isinstance(state["catalog_actions"], dict) else {}
    owner = actions.get("owner_rules")
    if command not in COMMANDS | (set(OWNER_PARAMETERS) if owner else set()) or not isinstance(
        args, dict
    ):
        raise ValueError("Неизвестное игровое действие.")
    allowed, required = (OWNER_PARAMETERS if command in OWNER_PARAMETERS else PARAMETERS)[command]
    if not required <= args.keys() <= allowed:
        raise ValueError("Неверные параметры игрового действия.")
    if command == "overcast" and args.get("payment") not in ("hp", "exhaustion"):
        raise ValueError("Нужен явный выбор цены перерасхода.")
    if command == "attempt":
        if not actions.get("attempt_plans"):
            raise ValueError("Свободные планы не включены для этой кампании.")
        validate_plan(args["plan"])
    if (
        any(
            plan.get(k)
            for k in (
                "steps",
                "places",
                "catalog",
                "queries",
                "attempt",
                "trade",
                "assessment",
                "reply",
                "memories",
            )
        )
        or plan.get("check") != "none"
    ):
        raise ValueError("Игровая заявка требует отдельного шага без готового исхода.")
    return {"command": command, "args": args}


@catalog.for_session
def planning_context(session, query=""):
    """Bounded available options, no private NPC wallets, global stocks or hidden events."""
    s = session.gameplay
    lv = level(s["xp"])

    def options(ids):
        from rpg_vkr.domain.catalog_search import ranked

        rows = [catalog.row(k) for k in ids]
        rows = ranked(rows, query, limit=16)
        return [
            {
                k: r[k]
                for k in (
                    "id",
                    "name",
                    "level",
                    "mp",
                    "cost_st",
                    "effects",
                    "ingredients",
                    "outputs",
                    "station",
                    "materials_by_output",
                    "requires_ammunition",
                    "requires_repair_material",
                )
                if k in r
            }
            for r in rows[:16]
        ]

    scene = session.interaction_state()
    return {
        "commands": sorted(
            (
                COMMANDS
                if s.get("catalog_revision") == 3
                else COMMANDS - {"flee", "first_aid", "contract", "faction"}
            )
            - ({"attempt"} if s.get("free_action_policy") != 1 else set())
            | (set(OWNER_PARAMETERS) if s.get("owner_rules_policy") == 1 else set())
        ),
        "spells": options(s["spells"]),
        **(
            {
                "owner_rules": {
                    "version": 1,
                    "hero_life": s.get("owner_life", {}).get("hero", {}),
                    "overcast": "Только известное заклинание, нехватка1–3MP. Явно выбранная цена: "
                    "2HP/MP (можно до0HP) или ceil(нехватка/2) истощения (6 — смерть). "
                    "Цена сохраняется при провале. Не выбирай способ оплаты за игрока.",
                    "npc_agreement": "Неизвестные полномочия и ограничения сначала уточняются.",
                }
            }
            if s.get("owner_rules_policy") == 1
            else {}
        ),
        "contracts": public_contracts(session) if s.get("catalog_revision") == 3 else [],
        "abilities": options([k for k in s["talents"] if k.startswith("talent_")]),
        "recipes": options(s["known_recipes"]),
        "learn_candidates": options(
            [
                r["id"]
                for kind in ("recipe", "spell")
                for r in catalog.available(kind, lv)
                if r["id"] not in s["known_recipes"] + s["spells"]
                and (kind != "spell" or s["mp_cap"])
            ]
        ),
        "resources": options(
            [r["id"] for r in catalog.available("material", lv) if r["process"] == 0]
        ),
        "destinations": [
            {"id": p.id, "name": p.name}
            for p in scene.places
            if p.parent == scene.current or scene.place().parent == p.id
        ],
        **(
            {
                "attempt_plans": {
                    "physical_items": public_facts(session),
                    "operations": [
                        "transform",
                        "repair",
                        "restore",
                        "use",
                        "magic",
                        "take",
                        "move",
                        "explore",
                    ],
                    "forms": {
                        k: {"name": v.name, "requires": list(v.requires), "tools": list(v.tools)}
                        for k, v in FORMS.items()
                    },
                    "schema": {
                        "operation": "primitive",
                        "goal": "form_or_affordance_or_place_id",
                        "items": ["real_id"],
                        "tool": "real_id_or_empty",
                    },
                }
            }
            if s.get("free_action_policy") == 1
            else {}
        ),
    }


GUIDE = (
    "Для нестандартных действий при attempt_plans предложи gameplay:"
    "{command:'attempt',args:{version:1,plan:{operation,goal,items,tool}}}. "
    "Это композиция общих операций и реальных ID, не готовый результат. "
    "Не назначай DC, свойства материалов, урон, награды или успешность. "
    "При наличии catalog_actions используй для магии, ремесла, добычи, боя, предметов, "
    "исследования и изучения поле gameplay:{command,args}. command — только из commands; "
    'ID бери из текущего состояния. Например gameplay:{"command":"cast",'
    '"args":{"spell":"light","target":"hero"}}. '
    "Неизученные техники требуют research:{entry:ID}; "
    "изготовление manufacture:{recipe:ID,result:ID}. "
    "Для repair укажи item; для gather material и quantity. "
    "Не придумывай товары, XP, HP или доступ. "
    'При gameplay: steps:[],places:[],check:"none", остальные действия и reply отсутствуют. '
    "Это только предложение: движок проверит ресурсы и цели и рассчитает квитанцию; "
    "исход заранее не описывай."
)


@catalog.for_session
def describe_proposal(session, proposal):
    verbs = {
        "cast": "Применить заклинание",
        "ability": "Применить способность",
        "consume": "Использовать предмет",
        "manufacture": "Изготовить",
        "repair": "Отремонтировать",
        "research": "Изучить",
        "gather": "Добыть сырьё",
        "equip": "Изменить снаряжение",
        "rest": "Отдохнуть",
        "wait": "Подождать",
        "encounter": "Начать схватку",
        "attack": "Атаковать",
        "recover": "Перевести дух",
        "dodge": "Уклониться",
        "buy": "Купить",
        "sell": "Продать",
        "explore": "Исследовать окрестности",
        "travel": "Отправиться",
        "flee": "Отступить",
        "first_aid": "Оказать первую помощь",
        "stabilize": "Стабилизировать при0HP",
        "death_save": "Выполнить спасбросок смерти",
        "food_terms": "Уточнить условия распределения",
        "overcast": "Применить магию с опасным перерасходом",
        "contract": "Поручение",
        "faction": "Объединение",
    }
    names = {r["id"]: r["name"] for r in catalog.load().values()}
    scene = session.interaction_state()
    names.update({t.id: t.name for t in scene.things})
    names.update({a.id: a.name for a in scene.actor_refs})
    names.update({p.id: p.name for p in scene.places})
    names["hero"] = "Герой"
    names.update({q["id"]: q["title"] for q in public_contracts(session)})
    names.update({k: f["name"] for k, f in session.gameplay.get("known_factions", {}).items()})
    operations = {
        "accept": "принять",
        "complete": "сдать добытое",
        "cancel": "отменить",
        "join": "вступить",
        "leave": "покинуть",
        "donate": "передать взнос",
    }
    if proposal["command"] == "attempt":
        plan = validate_plan(proposal["args"]["plan"])
        labels = {
            "transform": "Переделать",
            "repair": "Отремонтировать",
            "restore": "Восстановить прежнюю форму",
            "use": "Применить",
            "magic": "Попробовать магический эффект",
            "take": "Подобрать",
            "move": "Перейти",
            "explore": "Исследовать",
        }
        goal = FORMS[plan["goal"]].name if plan["goal"] in FORMS else names.get(plan["goal"], "")
        return (
            labels[plan["operation"]]
            + ": "
            + ", ".join(names.get(id, id) for id in plan["items"])
            + (" → " + goal if goal else "")
            + ("; инструмент: " + names.get(plan["tool"], plan["tool"]) if plan["tool"] else "")
            + ". Изменения предметов и затраты сохранятся в мире."
        )
    values = []
    for key, value in proposal["args"].items():
        if key == "operation":
            values.append(operations.get(value, "выбранное действие"))
        elif key == "payment":
            values.append(
                {
                    "hp": "цена2HP за1MP, вплоть до потери сознания",
                    "exhaustion": "цена истощением,6уровней — смерть",
                }.get(value, value)
            )
        elif key == "amount":
            values.append(f"{value} медных")
        elif key in ("quality", "quantity", "minutes"):
            values.append(f"{value} " + ("мин." if key == "minutes" else "ед."))
        elif isinstance(value, str):
            values.append(names.get(value, "выбранная цель"))
        elif isinstance(value, list):
            values.extend(names.get(v, "выбранная цель") for v in value)
    return verbs.get(proposal["command"], "Выполнить действие") + ": " + ", ".join(values)
