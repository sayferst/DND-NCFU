"""Closed AI action proposals; only Session commits resource changes."""

from rpg_vkr.domain import game_catalog as catalog
from rpg_vkr.domain.catalog_actions_v2 import PARAMETERS
from rpg_vkr.domain.contracts import public as public_contracts
from rpg_vkr.domain.unified import level

# Development/state management commands are never part of the model protocol.
COMMANDS = set(PARAMETERS) - {"advance", "check", "raise", "talent", "trade_world"}


def validate_proposal(value, plan, state):
    if (
        not state.get("catalog_actions")
        or not isinstance(value, dict)
        or set(value) != {"command", "args"}
    ):
        raise ValueError("Заявка единой механики недоступна.")
    command, args = value["command"], value["args"]
    if command not in COMMANDS or not isinstance(args, dict):
        raise ValueError("Неизвестное игровое действие.")
    allowed, required = PARAMETERS[command]
    if not required <= args.keys() <= allowed:
        raise ValueError("Неверные параметры игрового действия.")
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
            COMMANDS
            if s.get("catalog_revision") == 3
            else COMMANDS - {"flee", "first_aid", "contract", "faction"}
        ),
        "spells": options(s["spells"]),
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
    }


GUIDE = (
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
    }
    names = {r["id"]: r["name"] for r in catalog.load().values()}
    scene = session.interaction_state()
    names.update({t.id: t.name for t in scene.things})
    names.update({a.id: a.name for a in scene.actor_refs})
    names.update({p.id: p.name for p in scene.places})
    names["hero"] = "Герой"
    values = []
    for key, value in proposal["args"].items():
        if key in ("quality", "quantity", "minutes"):
            values.append(f"{value} " + ("мин." if key == "minutes" else "ед."))
        elif isinstance(value, str):
            values.append(names.get(value, "выбранная цель"))
        elif isinstance(value, list):
            values.extend(names.get(v, "выбранная цель") for v in value)
    return verbs.get(proposal["command"], "Выполнить действие") + ": " + ", ".join(values)
