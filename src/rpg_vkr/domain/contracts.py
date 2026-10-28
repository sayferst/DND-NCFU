"""Funded, verified NPC work. Prose never creates rewards or completes a task."""

import hashlib

from rpg_vkr.domain import game_catalog as content


def _offers(state, catalog, scene):
    definitions = {d.id: d for d in catalog.definitions}
    result = []
    quests = state.get("contracts", {})
    activity = state.get("activity", {})
    day = state["minute"] // 1440
    for actor in catalog.entities:
        spec = definitions[actor.definition_id]
        if (
            spec.kind != "actor"
            or actor.parent_id != scene.current
            or (actor.state or {}).get("hp", spec.properties.get("hp_max", 1)) <= 0
        ):
            continue
        if "npcs" not in spec.categories and not spec.properties.get("can_trade"):
            continue
        job = state["living_world"]["residents"].get(actor.id, {}).get("job", "resident")
        stock = state["living_world"]["stocks"][scene.current]
        resource = "mat_0_0" if job in ("smith", "miner", "artisan") else "mat_2_0"
        if stock[resource] >= 12:
            continue
        task = "gather"
        quantity = 2
        key = "q_" + hashlib.sha256(f"{actor.id}:{resource}:{day}".encode()).hexdigest()[:24]
        if key in quests or "contract:" + key in state["achievements"]:
            continue
        if any(q["npc"] == actor.id and q["status"] == "accepted" for q in quests.values()):
            continue
        value = content.row(resource)["price_cp"] * quantity
        reward = min(value * 3 // 2, max(0, (actor.state or {}).get("gold_cp", 0) // 3))
        result.append(
            {
                "id": key,
                "npc": actor.id,
                "npc_name": spec.name,
                "kind": task,
                "resource": resource,
                "quantity": quantity,
                "reward_cp": reward,
                "xp": 30,
                "place": scene.current,
                "created_day": day,
                "deadline": state["minute"] + 14 * 1440,
                "title": "Добыть и доставить: " + content.row(resource)["name"] + f" ×{quantity}",
                "baseline": activity.get("gathered", {}).get(resource, 0),
            }
        )
    return result


def offers(session):
    if (
        not getattr(session, "is_unified", False)
        or session.gameplay.get("catalog_revision") != 3
        or not session.catalog
    ):
        return []
    with content.using(3):
        return _offers(session.gameplay, session.catalog, session.interaction_state())


def public(session):
    visible = offers(session)
    current = session.interaction_state().current
    last = session.turns[-1].gameplay if session.turns else {}
    last = last or {}
    completed = (
        last.get("args", {}).get("offer")
        if last.get("command") == "contract" and last.get("args", {}).get("operation") == "complete"
        else None
    )
    active = [
        q
        for q in session.gameplay.get("contracts", {}).values()
        if q["place"] == current and (q["status"] == "accepted" or q["id"] == completed)
    ]
    return [
        {
            k: q[k]
            for k in (
                "id",
                "npc",
                "npc_name",
                "title",
                "kind",
                "resource",
                "quantity",
                "reward_cp",
                "xp",
                "deadline",
            )
        }
        | {"status": q.get("status", "offered")}
        for q in visible + active
    ]


def perform(e, args):
    if e.state.get("catalog_revision") != 3 or e.state["battle"]:
        raise ValueError("Поручение сейчас недоступно.")
    operation = args["operation"]
    key = args["offer"]
    quests = e.state.setdefault("contracts", {})
    if operation == "accept":
        offer = next((q for q in _offers(e.state, e.catalog, e.scene) if q["id"] == key), None)
        if offer is None:
            raise ValueError("Предложение устарело или недоступно.")
        actor, _ = e.actor(offer["npc"])
        wallet = dict(actor.state or {})
        if wallet.get("gold_cp", 0) < offer["reward_cp"]:
            raise ValueError("Награда не обеспечена средствами заказчика.")
        wallet["gold_cp"] = wallet.get("gold_cp", 0) - offer["reward_cp"]
        from dataclasses import replace

        e.actors[actor.id] = replace(actor, state=wallet)
        quests[key] = offer | {"status": "accepted", "escrow_cp": offer["reward_cp"]}
        e.text.append(
            "Поручение принято. Награда зарезервирована: " + str(offer["reward_cp"]) + " медных."
        )
        return
    quest = quests.get(key)
    if not quest or quest["status"] != "accepted":
        raise ValueError("Нет действующего поручения.")
    if operation == "cancel":
        refund(e, quest, "cancelled")
        e.text.append("Поручение отменено. Резерв возвращён заказчику.")
        return
    if operation != "complete":
        raise ValueError("Неизвестное действие с поручением.")
    e.actor(quest["npc"])
    if e.refs[quest["npc"]].place != e.scene.current:
        raise ValueError("Заказчика нет рядом.")
    if e.state["minute"] >= quest["deadline"]:
        raise ValueError("Срок поручения истёк.")
    gathered = e.state["activity"]["gathered"].get(quest["resource"], 0) - quest["baseline"]
    if gathered < quest["quantity"]:
        raise ValueError("Нужно действительно добыть материал после принятия поручения.")
    material = e.require_materials({quest["resource"]: quest["quantity"]})
    for item, number in material:
        e.consume_item(item, number)
    e.state["living_world"]["stocks"][quest["place"]][quest["resource"]] += quest["quantity"]
    e.state["copper"] += quest["escrow_cp"]
    quest["escrow_cp"] = 0
    quest["status"] = "completed"
    e.award("contract:" + key, quest["xp"])
    e.events.append(
        {
            "kind": "contract_completed",
            "id": key,
            "npc": quest["npc"],
            "reward_cp": quest["reward_cp"],
            "xp": quest["xp"],
        }
    )
    e.text.append(
        "Поручение выполнено: " + str(quest["reward_cp"]) + " медных, " + str(quest["xp"]) + " XP."
    )


def refund(e, quest, status):
    from rpg_vkr.domain.catalog_world import _wallet

    if quest["escrow_cp"]:
        if quest["npc"] in e.actors:
            _wallet(e, quest["npc"], quest["escrow_cp"])
        else:
            e.state["living_world"]["treasury_cp"] += quest["escrow_cp"]
    quest["escrow_cp"] = 0
    quest["status"] = status


def expire(e):
    for q in e.state.get("contracts", {}).values():
        if q["status"] == "accepted" and e.state["minute"] >= q["deadline"]:
            refund(e, q, "expired")
            if q["place"] == e.scene.current:
                e.text.append("Срок поручения истёк; резерв награды возвращён заказчику.")


def faction_action(e, args):
    if e.state.get("catalog_revision") != 3 or e.state["battle"]:
        raise ValueError("Действие объединения сейчас недоступно.")
    id = args["faction"]
    op = args["operation"]
    if id not in e.state["known_factions"]:
        raise ValueError("Это объединение пока неизвестно.")
    f = e.state["factions_v3"][id]
    if not any(
        m in e.refs and e.refs[m].place == e.scene.current and e.hp(m) > 0 for m in f["members"]
    ):
        raise ValueError("Представителя объединения нет рядом.")
    members = e.state.setdefault("memberships", [])
    if op == "leave":
        if id not in members:
            raise ValueError("Герой не состоит в объединении.")
        members.remove(id)
        e.text.append("Герой покинул объединение.")
        return
    amount = 10 if op == "join" else args.get("amount") if op == "donate" else None
    if type(amount) is not int or not 1 <= amount <= 1000 or e.state["copper"] < amount:
        raise ValueError("Недостаточно монет или неверная сумма взноса.")
    if op == "join":
        if id in members:
            raise ValueError("Герой уже состоит в объединении.")
        members.append(id)
    e.state["copper"] -= amount
    f["treasury_cp"] += amount
    f["reputation"] = min(100, f["reputation"] + 1)
    e.text.append("В объединение передано " + str(amount) + " медных.")
