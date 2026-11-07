"""Small declared-scenario reference engine, not a claim of executing production Engine9."""

from copy import deepcopy
from fractions import Fraction

KINDS = (
    "attack",
    "save",
    "advantage",
    "disadvantage",
    "damage",
    "heal",
    "movement",
    "spell_slot",
    "cantrip",
    "concentration",
    "death_save",
    "nonlethal",
    "ranged",
    "bonus_action",
    "reaction",
    "inventory",
    "charges",
    "rest",
    "duration",
    "skill",
    "door",
    "trap",
    "quest",
    "reward",
    "unknown",
    "craft",
    "repair",
    "ability",
    "overcast",
    "social",
    "catalog_lookup",
    "damage_zero",
    "stabilize",
)


def resolve(kind, p, before):
    """Resolve an explicit scenario; an eligibility question never commits its changes."""
    s = deepcopy(before)
    n = {}
    ok = True
    if kind in ("attack", "save", "skill", "door", "trap"):
        total = p["roll"] + p["modifier"]
        ok = total >= p["threshold"]
        n = {"total": total, "threshold": p["threshold"], "success": ok}
        if kind == "attack":
            damage = p["damage"] if ok else 0
            s["hp"] = max(0, s["hp"] - damage)
            n.update(damage=damage, hp_after=s["hp"])
        elif kind == "door" and ok:
            s["locked"] = False
        elif kind == "trap" and not ok:
            s["hp"] = max(0, s["hp"] - p["damage"])
            n["damage"] = p["damage"]
    elif kind in ("advantage", "disadvantage"):
        chosen = (max if kind == "advantage" else min)(p["dice"])
        total = chosen + p["modifier"]
        ok = total >= p["threshold"]
        n = {"chosen_die": chosen, "total": total, "threshold": p["threshold"], "success": ok}
    elif kind == "damage":
        raw = p["raw"]
        multiplier = (
            Fraction(0)
            if p["immune"]
            else Fraction(1, 2)
            if p["resistant"]
            else Fraction(2)
            if p["vulnerable"]
            else Fraction(1)
        )
        damage = int(raw * multiplier)
        s["hp"] = max(0, s["hp"] - damage)
        n = {"raw": raw, "damage": damage, "hp_after": s["hp"]}
    elif kind == "heal":
        gain = min(p["healing"], s["hp_max"] - s["hp"])
        s["hp"] += gain
        n = {"healed": gain, "hp_after": s["hp"]}
    elif kind == "movement":
        left = s["speed"] - s["movement_spent"]
        cost = p["distance"] * p["terrain_cost"]
        ok = cost <= left
        n = {
            "remaining_before": left,
            "required": cost,
            "max_path": min(p["distance"], left // p["terrain_cost"]),
            "can_reach": ok,
        }
        if ok:
            s["movement_spent"] += cost
            s["place"] = p["destination"]
    elif kind in ("spell_slot", "cantrip"):
        ok = p["known"] and (
            kind == "cantrip" or s["slot_level"] >= p["spell_level"] and s["slots"] > 0
        )
        if ok and kind == "spell_slot":
            s["slots"] -= 1
        n = {"can_cast": ok, "slots_after": s["slots"]}
    elif kind == "concentration":
        dc = max(10, p["damage"] // 2)
        passed = p["save_total"] >= dc
        if not passed:
            s["concentration"] = None
        if p["new_spell_cast"]:
            s["concentration"] = p["new_spell"]
        n = {"dc": dc, "save_success": passed, "concentration": s["concentration"]}
    elif kind == "death_save":
        f = s["failures"]
        v = s["successes"]
        roll = p["roll"]
        if roll == 20:
            s.update(hp=1, failures=0, successes=0, stable=False, conscious=True)
        else:
            if roll == 1:
                f += 2
            elif roll < 10:
                f += 1
            else:
                v += 1
            s.update(failures=f, successes=v)
            if f >= 3:
                s["dead"] = True
                s["stable"] = False
            elif v >= 3:
                s.update(stable=True, failures=0, successes=0)
        n = {
            "failures_accumulated": f,
            "successes_accumulated": v,
            "hp_after": s["hp"],
            "dead": s["dead"],
            "stable": s["stable"],
        }
    elif kind == "nonlethal":
        s["hp"] = max(0, s["hp"] - p["damage"])
        if s["hp"] == 0:
            s.update(stable=True, conscious=False, failures=0, successes=0)
        n = {"damage": p["damage"], "hp_after": s["hp"], "stable": s["stable"]}
    elif kind == "damage_zero":
        added = 2 if p["critical"] else 1
        s.update(stable=False, failures=s["failures"] + added)
        if p["raw"] >= s["hp_max"] or s["failures"] >= 3:
            s["dead"] = True
        n = dict(
            added_failures=added,
            failures=s["failures"],
            dead=s["dead"],
            instant_death=p["raw"] >= s["hp_max"],
        )
    elif kind == "stabilize":
        ok = p["roll"] + p["modifier"] >= p["threshold"]
        if ok:
            s.update(stable=True, failures=0, successes=0)
        n = dict(total=p["roll"] + p["modifier"], stabilized=ok)
    elif kind == "ranged":
        distance = p["distance"]
        ok = distance <= p["maximum"]
        n = {"can_attack": ok, "disadvantage": p["normal"] < distance <= p["maximum"]}
    elif kind in ("bonus_action", "reaction"):
        field = "bonus_left" if kind == "bonus_action" else "reaction_left"
        ok = s[field] > 0
        if ok:
            s[field] -= 1
        n = {"available": ok, "remaining": s[field]}
    elif kind == "inventory":
        ok = s["holder"] == p["actor"]
        if ok:
            s["holder"] = p["recipient"]
        n = {"transfer_possible": ok, "holder": s["holder"]}
    elif kind == "charges":
        active = min(s["charges"], p["uses"])
        s["charges"] -= active
        n = {"activations": active, "charges_after": s["charges"]}
    elif kind == "rest":
        s["hp"] = s["hp_max"]
        s["slots"] = s["slots_max"]
        s["exhaustion"] = max(0, s["exhaustion"] - 1)
        n = {"hp_after": s["hp"], "slots_after": s["slots"], "exhaustion_after": s["exhaustion"]}
    elif kind == "duration":
        s["duration"] = max(0, s["duration"] - p["elapsed"])
        s["effect_active"] = s["duration"] > 0
        n = {"remaining": s["duration"], "active": s["effect_active"]}
    elif kind == "quest":
        s["condition_met"] = p["returned_and_accepted"]
        n = {"condition_met": s["condition_met"], "paid": False}
    elif kind == "reward":
        ok = s["condition_met"] and s["npc_coins"] >= p["amount"]
        if ok:
            s["coins"] += p["amount"]
            s["npc_coins"] -= p["amount"]
        n = {"paid": ok, "coins_after": s["coins"], "npc_coins_after": s["npc_coins"]}
    elif kind == "overcast":
        missing = max(0, p["mp_cost"] - s["mp"])
        hp_cost = missing * 2 if p["payment"] == "hp" else 0
        exhaustion_cost = (missing + 1) // 2 if p["payment"] == "exhaustion" else 0
        ok = (
            p["known"]
            and missing <= 3
            and (missing == 0 or p["consent"])
            and (missing == 0 or p["payment"] == "exhaustion" or s["hp"] >= hp_cost)
        )
        if ok:
            s["mp"] = max(0, s["mp"] - p["mp_cost"])
            s["hp"] -= hp_cost
            s["exhaustion"] = min(6, s["exhaustion"] + exhaustion_cost)
            if s["exhaustion"] == 6:
                s.update(dead=True, conscious=False)
        n = dict(
            attempt_possible=ok,
            missing=missing,
            hp_cost=hp_cost,
            exhaustion_cost=exhaustion_cost,
            outcome="success"
            if ok and p["roll"] + p["modifier"] >= p["threshold"]
            else "failure"
            if ok
            else "blocked",
        )
    elif kind == "social":
        clarified = p["constraints_known"] and p["authority_known"]
        eligible = clarified and p["authority"] and p["feasible"] and not p["vital_violated"]
        ok = eligible and p["roll"] + p["modifier"] >= p["threshold"]
        s["npc_agreed"] = bool(ok)
        n = dict(
            total=p["roll"] + p["modifier"],
            eligible=eligible,
            clarification_required=not clarified,
            agreed=bool(ok),
        )
    elif kind == "catalog_lookup":
        n = {"name": p["name"], "category": p["category"], "details_available": False}
    elif kind == "unknown":
        n = {"established": p["question_fact"] in s["known_facts"]}
        ok = n["established"]
    elif kind in ("craft", "repair"):
        ok = (
            s["materials"] >= p["needed"]
            and p["tools_available"]
            and p["supported"]
            and s["stamina"] >= p["stamina_cost"]
        )
        outcome = "blocked"
        if ok:
            s["materials"] -= p["needed"]
            s["stamina"] -= p["stamina_cost"]
            margin = p["roll"] + p["modifier"] - p["threshold"]
            outcome = (
                "success"
                if margin >= 0
                else "partial"
                if margin >= -3 and p["partial_allowed"]
                else "failure"
            )
            if outcome == "success":
                s["quality"] = "usable"
            elif outcome == "partial":
                s["quality"] = "unfinished"
        n = {
            "attempt_possible": ok,
            "outcome": outcome,
            "materials_after": s["materials"],
            "stamina_after": s["stamina"],
            "quality": s["quality"],
        }
    elif kind == "ability":
        n = {
            "attempt_possible": True,
            "goal_reachable": p["required_capability"] in s["capabilities"],
            "d20_required": False,
        }
        ok = n["goal_reachable"]
    else:
        raise ValueError("Unsupported reference operation: " + kind)
    if s["hp"] == 0:
        s["conscious"] = False
    if kind == "heal" and s["hp"] > 0:
        s.update(conscious=True, stable=False, failures=0, successes=0)
    if p.get("intent_only", False):
        predicted = deepcopy(s)
        s = deepcopy(before)
    else:
        predicted = None
    return {
        "operation": kind,
        "parameters": deepcopy(p),
        "numbers": n,
        "success": ok,
        "committed": not p.get("intent_only", False),
        "state_after": s,
        "predicted_state_if_executed": predicted,
        "producer": "synthetic_reference_not_production_engine9",
    }
