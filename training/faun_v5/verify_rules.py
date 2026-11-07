"""Independent event replay: integer budgets and unit packets, not generator functions."""

from copy import deepcopy


def verify(kind, p, b, r):
    s = deepcopy(b)
    ok = True
    n = {}
    if kind in ("attack", "save", "skill", "door", "trap"):
        total = sum((p["roll"], p["modifier"]))
        ok = not total < p["threshold"]
        n.update(total=total, threshold=p["threshold"], success=ok)
        if kind == "attack":
            lost = sum(1 for _ in range(p["damage"])) if ok else 0
            s["hp"] = max(0, b["hp"] - lost)
            n.update(damage=lost, hp_after=s["hp"])
        if kind == "door" and ok:
            s["locked"] = False
        if kind == "trap" and not ok:
            s["hp"] = max(0, b["hp"] - p["damage"])
            n["damage"] = p["damage"]
    elif kind in ("advantage", "disadvantage"):
        ordered = sorted(p["dice"])
        chosen = ordered[-1 if kind == "advantage" else 0]
        total = sum((chosen, p["modifier"]))
        ok = total >= p["threshold"]
        n = dict(chosen_die=chosen, total=total, threshold=p["threshold"], success=ok)
    elif kind == "damage":
        packets = list(range(p["raw"]))
        if p["immune"]:
            damage = 0
        elif p["resistant"]:
            damage = len(list(zip(packets[::2], packets[1::2], strict=False)))
        elif p["vulnerable"]:
            damage = len(packets + packets)
        else:
            damage = len(packets)
        s["hp"] = max(0, b["hp"] - damage)
        n = dict(raw=p["raw"], damage=damage, hp_after=s["hp"])
    elif kind == "heal":
        for _ in range(p["healing"]):
            if s["hp"] < s["hp_max"]:
                s["hp"] += 1
        n = dict(healed=s["hp"] - b["hp"], hp_after=s["hp"])
    elif kind == "movement":
        budget = b["speed"] - b["movement_spent"]
        walked = 0
        remaining = budget
        for _ in range(p["distance"]):
            if remaining < p["terrain_cost"]:
                break
            remaining -= p["terrain_cost"]
            walked += 1
        ok = walked == p["distance"]
        n = dict(
            remaining_before=budget,
            required=p["distance"] * p["terrain_cost"],
            max_path=walked,
            can_reach=ok,
        )
        if ok:
            s["movement_spent"] = b["speed"] - remaining
            s["place"] = p["destination"]
    elif kind in ("spell_slot", "cantrip"):
        usable = (
            []
            if kind == "cantrip"
            else [b["slot_level"] for _ in range(b["slots"]) if b["slot_level"] >= p["spell_level"]]
        )
        ok = p["known"] and (kind == "cantrip" or bool(usable))
        if ok and kind == "spell_slot":
            s["slots"] -= 1
        n = dict(can_cast=ok, slots_after=s["slots"])
    elif kind == "concentration":
        dc = max(10, int(p["damage"] / 2))
        passed = not p["save_total"] < dc
        if not passed:
            s["concentration"] = None
        if p["new_spell_cast"]:
            s["concentration"] = p["new_spell"]
        n = dict(dc=dc, save_success=passed, concentration=s["concentration"])
    elif kind == "death_save":
        failures = [False] * b["failures"]
        successes = [True] * b["successes"]
        roll = p["roll"]
        if roll == 20:
            s.update(hp=1, failures=0, successes=0, stable=False, conscious=True)
        else:
            if roll == 1:
                failures.extend([False, False])
            elif roll < 10:
                failures.append(False)
            else:
                successes.append(True)
            s.update(failures=len(failures), successes=len(successes))
            if len(failures) >= 3:
                s.update(dead=True, stable=False)
            elif len(successes) >= 3:
                s.update(stable=True, failures=0, successes=0)
        n = dict(
            failures_accumulated=len(failures),
            successes_accumulated=len(successes),
            hp_after=s["hp"],
            dead=s["dead"],
            stable=s["stable"],
        )
    elif kind == "nonlethal":
        s["hp"] = max(0, b["hp"] - p["damage"])
        if not s["hp"]:
            s.update(stable=True, conscious=False, failures=0, successes=0)
        n = dict(damage=p["damage"], hp_after=s["hp"], stable=s["stable"])
    elif kind == "damage_zero":
        added = len([0, 0] if p["critical"] else [0])
        s["failures"] = b["failures"] + added
        s["stable"] = False
        massive = not p["raw"] < b["hp_max"]
        s["dead"] = massive or s["failures"] > 2
        n = dict(
            added_failures=added, failures=s["failures"], dead=s["dead"], instant_death=massive
        )
    elif kind == "stabilize":
        ok = sum((p["roll"], p["modifier"])) >= p["threshold"]
        if ok:
            s["stable"] = True
            s["failures"] = s["successes"] = 0
        n = dict(total=sum((p["roll"], p["modifier"])), stabilized=ok)
    elif kind == "ranged":
        ok = p["distance"] in range(p["maximum"] + 1)
        n = dict(can_attack=ok, disadvantage=ok and p["distance"] not in range(p["normal"] + 1))
    elif kind in ("bonus_action", "reaction"):
        field = {"bonus_action": "bonus_left", "reaction": "reaction_left"}[kind]
        ok = bool(b[field])
        if ok:
            s[field] -= 1
        n = dict(available=ok, remaining=s[field])
    elif kind == "inventory":
        ok = b["holder"] == p["actor"]
        if ok:
            s["holder"] = p["recipient"]
        n = dict(transfer_possible=ok, holder=s["holder"])
    elif kind == "charges":
        activations = 0
        for _ in range(p["uses"]):
            if s["charges"]:
                s["charges"] -= 1
                activations += 1
        n = dict(activations=activations, charges_after=s["charges"])
    elif kind == "rest":
        s.update(hp=b["hp_max"], slots=b["slots_max"], exhaustion=max(0, b["exhaustion"] - 1))
        n = dict(hp_after=s["hp"], slots_after=s["slots"], exhaustion_after=s["exhaustion"])
    elif kind == "duration":
        for _ in range(p["elapsed"]):
            s["duration"] = max(0, s["duration"] - 1)
        s["effect_active"] = s["duration"] != 0
        n = dict(remaining=s["duration"], active=s["effect_active"])
    elif kind == "quest":
        s["condition_met"] = p["returned_and_accepted"]
        n = dict(condition_met=s["condition_met"], paid=False)
    elif kind == "reward":
        ok = b["condition_met"] and not b["npc_coins"] < p["amount"]
        if ok:
            for _ in range(p["amount"]):
                s["npc_coins"] -= 1
                s["coins"] += 1
        n = dict(paid=ok, coins_after=s["coins"], npc_coins_after=s["npc_coins"])
    elif kind == "unknown":
        ok = any(fact == p["question_fact"] for fact in b["known_facts"])
        n = dict(established=ok)
    elif kind in ("craft", "repair"):
        ok = (
            not b["materials"] < p["needed"]
            and p["tools_available"]
            and p["supported"]
            and b["stamina"] >= p["stamina_cost"]
        )
        outcome = "blocked"
        if ok:
            for _ in range(p["needed"]):
                s["materials"] -= 1
            s["stamina"] -= p["stamina_cost"]
            total = sum((p["roll"], p["modifier"]))
            if total >= p["threshold"]:
                outcome = "success"
                s["quality"] = "usable"
            elif p["partial_allowed"] and total >= p["threshold"] - 3:
                outcome = "partial"
                s["quality"] = "unfinished"
            else:
                outcome = "failure"
        n = dict(
            attempt_possible=ok,
            outcome=outcome,
            materials_after=s["materials"],
            stamina_after=s["stamina"],
            quality=s["quality"],
        )
    elif kind == "ability":
        ok = any(v == p["required_capability"] for v in b["capabilities"])
        n = dict(attempt_possible=True, goal_reachable=ok, d20_required=False)
    elif kind == "overcast":
        deficit = max(0, p["mp_cost"] - b["mp"])
        hp_price = sum(2 for _ in range(deficit)) if p["payment"] == "hp" else 0
        fatigue = len(list(range(0, deficit, 2))) if p["payment"] == "exhaustion" else 0
        ok = bool(
            p["known"]
            and deficit < 4
            and (not deficit or p["consent"])
            and (not deficit or p["payment"] == "exhaustion" or b["hp"] >= hp_price)
        )
        if ok:
            for _ in range(p["mp_cost"]):
                s["mp"] = max(0, s["mp"] - 1)
            s["hp"] -= hp_price
            s["exhaustion"] = min(6, b["exhaustion"] + fatigue)
            if s["exhaustion"] >= 6:
                s.update(dead=True, conscious=False)
        n = dict(
            attempt_possible=ok,
            missing=deficit,
            hp_cost=hp_price,
            exhaustion_cost=fatigue,
            outcome="blocked"
            if not ok
            else "failure"
            if sum((p["roll"], p["modifier"])) < p["threshold"]
            else "success",
        )
    elif kind == "social":
        clarified = bool(p["constraints_known"] and p["authority_known"])
        eligible = all((clarified, p["authority"], p["feasible"], not p["vital_violated"]))
        ok = bool(eligible and sum((p["roll"], p["modifier"])) >= p["threshold"])
        s["npc_agreed"] = ok
        n = dict(
            total=sum((p["roll"], p["modifier"])),
            eligible=eligible,
            clarification_required=not clarified,
            agreed=ok,
        )
    elif kind == "catalog_lookup":
        n = dict(name=p["name"], category=p["category"], details_available=False)
    else:
        raise ValueError("Unverified operation " + kind)
    if s["hp"] == 0:
        s["conscious"] = False
    if kind == "heal" and s["hp"] > 0:
        s.update(conscious=True, stable=False, failures=0, successes=0)
    predicted = None
    if p.get("intent_only"):
        predicted = deepcopy(s)
        s = deepcopy(b)
    if (
        r["numbers"] != n
        or r["success"] != ok
        or r["state_after"] != s
        or r["predicted_state_if_executed"] != predicted
    ):
        raise ValueError("Independent replay disagrees: " + kind)
    if r["committed"] == bool(p.get("intent_only")):
        raise ValueError("Intent commit mismatch")
    return True
