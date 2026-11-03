"""Consent-based rations: real settlement stocks, observed NPCs, persistent reactions."""

from dataclasses import replace

from rpg_vkr.domain.strategic_conflicts import FoodState, bayes, cooperative_belief, food_options


def execute(e, args):
    if (
        e.state.get("free_action_policy") != 1
        or not isinstance(args, dict)
        or set(args) != {"policy"}
        or args["policy"] not in ("civilians", "guards", "balanced")
    ):
        raise ValueError("Неверное предложение распределения.")
    if e.state["battle"]:
        raise ValueError("Переговоры требуют отдельного мирного контакта.")
    w = e.state["living_world"]
    here = [
        id
        for id, ref in e.refs.items()
        if ref.place == e.scene.current and e.hp(id) > 0 and id in w["residents"]
    ]
    guards = [id for id in here if w["residents"][id]["job"] == "guard"]
    civilians = [id for id in here if id not in guards]
    if not civilians or not guards:
        raise ValueError("Нужны присутствующие представители жителей и гарнизона.")
    key = f"{e.scene.current}:{w['day']}"
    if key in e.state.get("food_negotiations", {}):
        raise ValueError("На этот день распределение уже обсуждалось.")
    stock = w["stocks"][e.scene.current]
    # A ration tops up a resident to three units; existing personal food counts.
    needs = {id: max(0, 3 - w["residents"][id]["food"]) for id in here}
    model = FoodState(
        food=stock["food"],
        civilian_need=sum(needs[id] for id in civilians),
        guard_need=sum(needs[id] for id in guards),
        treasury=0,
        supplier_available=False,
        supplier_food=0,
    )
    if model.civilian_need + model.guard_need == 0:
        raise ValueError("Личные запасы участников уже обеспечивают рацион.")
    options = food_options(model)
    selected = options[args["policy"]]
    # New owner policy binds a feasible offer after success only within public vital limits.
    owner_policy = e.state.get("owner_rules_policy") == 1
    public_terms = {}
    eligible = True
    if owner_policy:
        for id in here:
            terms = (e.actors[id].state or {}).get("public_ration_terms")
            if (
                not terms
                or terms.get("scope_actor") != id
                or terms.get("authority_scope") != "own_ration"
            ):
                raise ValueError(
                    "CLARIFICATION_REQUIRED: сначала уточните полномочия и условия участников."
                )
            public_terms[id] = terms
        allocations_preview = {}
        for group, people in (("civilians", civilians), ("guards", guards)):
            remaining = selected["allocation"][group]
            allocations_preview.update(dict.fromkeys(people, 0))
            while remaining:
                for id in sorted(people):
                    if remaining and allocations_preview[id] < needs[id]:
                        allocations_preview[id] += 1
                        remaining -= 1
        eligible = all(
            w["residents"][id]["food"] + allocations_preview[id] >= public_terms[id]["minimum_food"]
            for id in here
        )
    e.action_minutes = 10
    persuasive = e.check("persuasion", 15) if eligible else False
    consent = {}
    for id in here:
        group = "garrison" if id in guards else "residents"
        relations = (e.actors[id].state or {}).get("strategic_relations", {})
        expectation = relations.get("expected_cooperation", 0.5)
        reservation = 0.35 + 0.2 * (1 - expectation)
        utility = selected["utilities"][group]
        consent[id] = {
            "accepted": (
                w["residents"][id]["food"] + allocations_preview[id]
                >= public_terms[id]["minimum_food"]
                if owner_policy
                else needs[id] == 0 or utility >= reservation
            ),
            "utility": utility,
            "reservation": reservation,
        }
    accepted = persuasive and all(r["accepted"] for r in consent.values())
    allocations = dict.fromkeys(here, 0)
    if accepted:
        for group, people in (("civilians", civilians), ("guards", guards)):
            remaining = selected["allocation"][group]
            # Round-robin distributes finite units fairly within each group.
            while remaining:
                for id in sorted(people):
                    if allocations[id] < needs[id] and remaining:
                        allocations[id] += 1
                        remaining -= 1
        for id, quantity in allocations.items():
            w["residents"][id]["food"] += quantity
        stock["food"] -= sum(allocations.values())
    reactions = {}
    for id in here:
        actor = e.actors[id]
        state = dict(actor.state or {})
        group = "garrison" if id in guards else "residents"
        utility = selected["utilities"][group]
        delta = (1 if utility >= 0.7 else -1) if accepted else 0
        relations = dict(state.get("strategic_relations", {}))
        relations["trust"] = max(-10, min(10, relations.get("trust", 0) + delta))
        relations["negotiations"] = relations.get("negotiations", 0) + 1
        relations["last_utility"] = utility
        if accepted:
            satisfied = allocations[id] >= needs[id]
            counter = "fulfilled" if satisfied else "disappointed"
            relations[counter] = relations.get(counter, 0) + 1
            prior = relations.get("beliefs", {"cooperative": 0.5, "self_interested": 0.5})
            relations["beliefs"] = bayes(
                prior,
                {
                    "cooperative": 0.8 if satisfied else 0.2,
                    "self_interested": 0.3 if satisfied else 0.7,
                },
            )
            relations["expected_cooperation"] = cooperative_belief(
                relations.get("fulfilled", 0), relations.get("disappointed", 0)
            )
        state["strategic_relations"] = relations
        e.actors[id] = replace(actor, state=state)
        reactions[id] = {"utility": utility, "trust_change": delta}
    record = {
        "version": "food-negotiation-1",
        "policy": args["policy"],
        "accepted": accepted,
        "consent": consent,
        "options": options,
        "transfers": allocations,
        "reactions": reactions,
        "food_before": model.food,
        "food_after": stock["food"],
    }
    e.state.setdefault("food_negotiations", {})[key] = record
    e.events.append({"kind": "food_negotiation", **record})
    e.text.append(
        "Согласовано распределение реальных припасов; порции переданы участникам."
        if accepted
        else "Предложение выслушано, но соглашение не достигнуто. Припасы не переданы."
    )


def disclose_terms(e):
    """Declared NPC interests over their own ration in the existing communal pool."""
    if e.state.get("owner_rules_policy") != 1 or e.state["battle"]:
        raise ValueError("Уточнение условий доступно в мирной сцене по новым правилам.")
    residents = e.state["living_world"]["residents"]
    people = [
        id
        for id, ref in e.refs.items()
        if ref.place == e.scene.current and id in residents and e.hp(id) > 0
    ]
    if not people:
        raise ValueError("Здесь нет участников распределения.")
    for id in people:
        actor, spec = e.actor(id)
        if spec.properties.get("shares_ration_terms", True) is False:
            continue
        minimum = spec.properties.get("minimum_ration", 2 if residents[id]["job"] == "guard" else 1)
        if type(minimum) is not int or not 0 <= minimum <= 3:
            raise ValueError("Некорректные условия NPC.")
        terms = {
            "version": "personal-ration-1",
            "authority_scope": "own_ration",
            "minimum_food": minimum,
            "scope_actor": id,
            "pool": "living_world.stocks:" + e.scene.current,
        }
        e.actors[id] = replace(actor, state=(actor.state or {}) | {"public_ration_terms": terms})
        e.events.append({"kind": "owner_food_terms", "actor": id, "terms": terms})
    e.text.append(
        "Участники назвали условия относительно своих собственных рационов; "
        "соглашение ещё не заключено."
    )
