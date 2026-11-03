"""Compile explicit synthetic scenes from curated intent annotations and shared rules.

This is a reference execution corpus, never a claim of replayed human campaigns.
Intent-specific prose belongs to declarative annotation data; all checks, costs,
identity conservation, missing-capability gates and ledgers use shared operators.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from random import Random

from rpg_vkr.domain import owner_rules
from rpg_vkr.domain.character import ability_modifier
from training.annotation_v2 import rows_v2
from training.jsonio import strict_json
from training.schema import digest

ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = ROOT / "training/curriculum/intents-v4.tsv"
SCHEMA = "gm-grounded-synthetic-v1"
POLICY = "grounded-synthetic-v1"
ROLL_OPS = {
    "craft",
    "shape",
    "coat",
    "join",
    "repair",
    "restore",
    "separate",
    "test",
    "deploy",
    "movement",
    "practice",
    "disarm",
    "attack",
    "negotiate",
    "service",
    "allocate",
    "supply",
    "barter",
    "stabilize",
    "overcast",
}
ITEM_OPS = {
    "craft",
    "shape",
    "coat",
    "join",
    "repair",
    "restore",
    "separate",
    "test",
    "deploy",
    "take",
    "transfer",
    "trade",
    "sell",
    "barter",
    "refund",
    "unequip",
    "scroll",
    "heal_item",
}
MAGIC_OPS = {"cast", "heal", "illusion", "sustain", "overcast", "dismiss", "dead_heal"}
AUTO_NO_CHANGE = {
    "noop",
    "stop",
    "proposal",
    "verify",
    "compare",
    "inform",
    "observe",
    "record",
    "clarify",
}
CRAFT_OPS = {"craft", "shape", "coat", "join", "repair", "restore", "separate", "deploy"}


SUPPORTED_OPERATIONS = (
    ROLL_OPS
    | ITEM_OPS
    | MAGIC_OPS
    | AUTO_NO_CHANGE
    | {"capability", "defend", "recover", "rest", "long_rest", "wait", "move", "choose"}
)


def specs():
    result = {}
    parameters = strict_json((SPEC_FILE.parent / "parameters-v4.json").read_bytes())
    for line in SPEC_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, operation, subject, goal, task, success, partial, failure = line.split("|")
        if operation not in SUPPORTED_OPERATIONS:
            raise ValueError("Unknown reference primitive")
        if key in result:
            raise ValueError("Duplicate intent annotation")
        result[key] = dict(
            operation=operation,
            subject=subject,
            goal=goal,
            task=task,
            success=success,
            partial=partial,
            failure=failure,
            parameters=parameters.get(key, {}),
        )
    if len(result) != 200:
        raise ValueError("Expected200 curated intents")
    return result


def seed_for(id):
    return int(hashlib.sha256(("grounded-v4:" + id).encode()).hexdigest()[:12], 16)


def initial(source, spec):
    variant = source["condition_type"]
    score = 14 - 2 * variant
    abilities = dict.fromkeys(
        ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"), 10
    )
    primary = ("dexterity", "intelligence", "intelligence", "dexterity", "wisdom")[variant]
    abilities[primary] = score
    # The original class/profile facts remain visible; capacities are explicit,
    # rather than a die roll silently granting a new spell or material.
    magical = variant in (1, 4)
    life = owner_rules.Life(14, 14, exhaustion=1 if spec["operation"] == "long_rest" else 0)
    target_life = (
        owner_rules.Life(0, 12)
        if spec["operation"] in ("stabilize", "dead_heal")
        else owner_rules.Life(5, 12)
    )
    if spec["operation"] == "dead_heal":
        target_life = owner_rules.Life(0, 12, dead=True)
    state = {
        "hero": {
            "abilities": abilities,
            "life": asdict(life),
            "mp": 0 if variant == 3 or not magical or spec["operation"] == "overcast" else 5,
            "mp_cap": 5 if magical else 0,
            "st": 1 if variant == 3 else 8,
            "st_cap": 8,
            "gold": 18 - variant,
            "arrows": 12 - variant,
            "xp": 1000 if spec["operation"] == "choose" else 0,
            "level": 5 if spec["operation"] == "choose" else 1,
            "known_effects": ["light", "heal"] if magical else [],
            "place": "yard",
            "talents": [],
        },
        "objects": {
            "subject": {
                "id": "subject",
                "name": spec["subject"],
                "quantity": 1,
                "holder": "counterparty"
                if spec["operation"] == "trade"
                else "yard"
                if spec["operation"] == "take"
                else "hero",
                "legal_owner": "smith" if spec["operation"] == "take" else "hero",
                "accessible": not (variant == 1 and spec["operation"] in ITEM_OPS),
                "container": "chest" if variant == 1 and spec["operation"] in ITEM_OPS else None,
                "durability": 2 if variant == 2 else 8,
                "maximum": 12,
                "properties": {
                    "flight": False,
                    "creates_currency": False,
                    "waterproof": False,
                    "repairable": True,
                    "material_available": True,
                },
            },
            "tool": {
                "id": "tool",
                "name": "объявленный инструмент",
                "quantity": 1,
                "holder": "hero",
                "legal_owner": "hero",
                "accessible": True,
                "durability": 2 if variant == 2 else 12,
                "maximum": 12,
            },
            "material": {
                "id": "material",
                "name": "расходный материал",
                "quantity": 1 if variant == 2 else 3,
                "holder": "hero",
                "legal_owner": "hero",
                "accessible": variant != 1,
                "durability": 1,
                "maximum": 1,
            },
        },
        "npc": {
            "id": "counterparty",
            "present": True,
            "gold": 30,
            "authority": True,
            "vital_constraints_known": True,
            "vital_constraints_satisfied": True,
            "stock": 3,
            "minimum_retained": 1,
            "agreed_price": 4,
            "agreement": False,
            "reported_knowledge": [],
        },
        "target_life": asdict(target_life),
        "route": {
            "id": "east_path",
            "origin": "yard",
            "destination": "destination",
            "destination_name": spec["goal"],
            "known": True,
            "open": True,
            "minutes": 7 + variant,
        },
        "world": {
            "minute": 480,
            "weather": "rain" if variant == 2 else "clear",
            "deadline": 490 if variant == 3 else None,
            "food": 100,
            "treasury": 40,
            "supplier_stock": 20,
            "supplier_price": 30,
            "civilian_need": 70,
            "garrison_need": 50,
        },
        "facts": {
            "selected_target": None if spec["operation"] == "clarify" else "subject",
            "two_similar_targets": variant == 4,
            "rumor_verified": False,
            "ownership_disputed": variant == 4,
            "door_open": True,
            "reward_already_recorded": True,
            "prior_material_spent": 1,
            "allowed_talents": ["resilient", "enduring"],
            "level_up_confirmed": spec["operation"] == "choose",
            "confirmed_place": "yard",
            "ordinary_magic_makes_gold": False,
            "flight_supported": False,
            "effect_registry": {
                "light": {"mp_cost": 1, "implemented": True, "duration_minutes": 10},
                "heal": {"mp_cost": 3, "implemented": True, "healing": 3},
            },
        },
    }

    params = spec.get("parameters", {})
    obj = state["objects"]["subject"]
    item = spec["operation"] in ITEM_OPS
    obj["kind"] = "item" if item else "topic"
    if not item:
        obj.update(holder="yard", legal_owner=None)
    obj.update({k: params[k] for k in ("holder", "legal_owner", "quantity") if k in params})
    obj["properties"]["capabilities"] = params.get("input_capabilities", [])
    obj["properties"]["traits"] = params.get("input_traits", ["workable_material"])
    if variant == 4:
        other = deepcopy(obj)
        other.update(id="similar_subject", name="другой похожий объект")
        state["objects"]["similar_subject"] = other
    if variant == 1 and params.get("requires_subject_access"):
        obj.update(accessible=False, container="chest")
    if params.get("closed_in_all_conditions"):
        obj.update(accessible=False, container="chest")
    state["objects"]["tool"]["capabilities"] = params.get(
        "tool_capabilities", ["cut", "shape", "repair", "bind", "abrasive"]
    )
    state["objects"]["tool"]["name"] = params.get("tool_name", "объявленный инструмент")
    obj["properties"]["origin_capabilities"] = (
        ["shoot"] if params.get("provenance") == "registered_former_bow" else []
    )
    state["facts"].update(
        transfer_destination=params.get("destination", "counterparty")
        if spec["operation"] == "transfer"
        else "counterparty",
        transfer_title=params.get("transfer_title", False),
        declared_evidence=params.get("evidence", {}),
        declared_limits=params.get("limits", {}),
        subject_equipped=spec["operation"] == "unequip",
        supported_effect_active=spec["operation"] in ("sustain", "dismiss"),
        supported_effect_owner="hero",
        overcast_payment_choice="hp" if spec["operation"] == "overcast" else None,
    )
    state["npc"]["vital_constraints_satisfied"] = params.get("vital_constraints_satisfied", True)
    state["npc"]["agreement"] = params.get("preexisting_agreement", False)
    if params.get("route_closed"):
        state["route"]["open"] = False
    if spec["operation"] in ("move", "movement") and params.get("destination"):
        state["route"]["destination"] = params["destination"]
    if params.get("target_unconscious"):
        state["target_life"] = asdict(owner_rules.Life(0, 12))
    if params.get("dependent_item"):
        state["objects"]["dependent"] = {
            "id": "dependent",
            "name": params["dependent_item"],
            "kind": "item",
            "quantity": 1,
            "holder": "hero",
            "legal_owner": "hero",
            "requires_component": "subject",
            "functional": True,
            "durability": 8,
            "maximum": 12,
            "accessible": True,
        }
    if spec["operation"] == "overcast" and magical:
        state["hero"]["life"]["hp"] = 2 if variant == 1 else 8
    if params.get("consumed_component"):
        state["objects"]["component"] = {
            "id": "component",
            "name": params["consumed_component"],
            "kind": "item",
            "quantity": 1,
            "holder": "subject",
            "legal_owner": "hero",
            "durability": 1,
            "maximum": 1,
            "accessible": True,
        }
    state["npc"]["offer_terms"] = {"goal": spec["goal"], "minutes": params.get("term_minutes", 60)}
    if spec["operation"] == "barter":
        state["objects"]["barter_item"] = {
            "id": "barter_item",
            "name": "предмет согласованного обмена",
            "kind": "item",
            "quantity": 1,
            "holder": "counterparty",
            "legal_owner": "counterparty",
            "durability": 8,
            "maximum": 12,
            "accessible": True,
        }
    if spec["operation"] == "disarm":
        state["objects"]["target_weapon"] = {
            "id": "target_weapon",
            "name": "оружие противника",
            "kind": "item",
            "quantity": 1,
            "holder": "opponent",
            "legal_owner": "opponent",
            "durability": 8,
            "maximum": 12,
            "accessible": True,
        }
    if any(obj.get("container") == "chest" for obj in state["objects"].values()):
        state["objects"]["chest"] = {
            "id": "chest",
            "name": "запертый сундук",
            "kind": "item",
            "quantity": 1,
            "holder": "yard",
            "legal_owner": "counterparty",
            "durability": 12,
            "maximum": 12,
            "accessible": True,
            "container": True,
            "locked": True,
            "open": False,
        }
        for obj in state["objects"].values():
            if obj.get("container") == "chest":
                obj["holder"] = "chest"
    if state["facts"]["transfer_destination"] == "open_pack":
        state["objects"]["open_pack"] = {
            "id": "open_pack",
            "name": "открытый рюкзак",
            "kind": "item",
            "quantity": 1,
            "holder": "hero",
            "legal_owner": "hero",
            "durability": 8,
            "maximum": 12,
            "accessible": True,
            "container": True,
            "locked": False,
            "open": True,
        }
    references = {
        "hero",
        "counterparty",
        state["hero"]["place"],
        state["route"]["destination"],
        state["facts"]["transfer_destination"],
    }
    references.update(obj.get("holder") for obj in state["objects"].values())
    references.update(obj.get("legal_owner") for obj in state["objects"].values())
    state["registered_entities"] = {
        id: {
            "id": id,
            "kind": "place"
            if id in (state["hero"]["place"], state["route"]["destination"])
            else "actor",
        }
        for id in sorted(references - set(state["objects"]) - {None})
    }
    return state


def possible_capabilities(before):
    obj = before["objects"]["subject"]
    traits = set(obj["properties"].get("traits", []))
    tools = set(before["objects"]["tool"].get("capabilities", []))
    conversions = {
        "fishing_support": ({"shaft", "cord"}, {"cut"}),
        "snare": ({"cord"}, {"bind"}),
        "line": ({"cord"}, set()),
        "rope": ({"cord"}, {"bind"}),
        "splint": ({"shaft", "binding"}, {"cut"}),
        "container_form": ({"plastic_material"}, {"shape"}),
        "water_resistant": ({"fabric", "oil"}, set()),
        "material_bundle": (set(), set()),
        "pointed_weapon": ({"shaft"}, {"cut"}),
        "support": ({"rigid"}, set()),
    }
    possible = {
        cap
        for cap, (inputs, required_tools) in conversions.items()
        if inputs <= traits and required_tools <= tools
    }
    possible.update(obj["properties"].get("origin_capabilities", []))
    return possible - {"currency", "gold_transmutation", "flight", "resurrection"}


def resolve(before, spec, seed):
    """Shared deterministic reference semantics, independent of wording and scenario ID."""
    if spec.get("operation") not in SUPPORTED_OPERATIONS:
        raise ValueError("Unknown reference primitive")
    state = deepcopy(before)
    hero = state["hero"]
    obj = state["objects"]["subject"]
    npc = state["npc"]
    world = state["world"]
    op = spec["operation"]
    result = {
        "provenance": "SYNTHETIC_REFERENCE_EXECUTION",
        "rules_version": owner_rules.VERSION,
        "operation": op,
        "subject_id": obj["id"],
        "goal": spec["goal"],
        "attempt_possible": True,
        "goal_reachable": True,
        "d20_required": False,
        "roll": None,
        "outcome": "success",
        "quality_cap": "limited"
        if before["world"]["weather"] == "rain" and op in CRAFT_OPS
        else "declared_goal_only",
        "limitations": ["No new resources or capabilities beyond registered inputs."],
    }
    text_key = "success"
    blocker = None
    if (op in ITEM_OPS or spec.get("parameters", {}).get("requires_subject_access")) and not obj[
        "accessible"
    ]:
        blocker = "closed_container"
    elif op == "clarify":
        blocker = "target_not_selected"
    elif op == "capability":
        required_capability = spec.get("parameters", {}).get("required_capability")
        if not required_capability or required_capability not in obj["properties"]["capabilities"]:
            blocker = "unsupported_capability"
    elif op in MAGIC_OPS and op != "dismiss":
        effect = spec.get("parameters", {}).get(
            "effect", {"heal": "heal", "dead_heal": "heal", "illusion": "illusion"}.get(op, "light")
        )
        if effect not in hero["known_effects"] or not state["facts"]["effect_registry"].get(
            effect, {}
        ).get("implemented"):
            blocker = "unknown_effect"
    elif op in ("negotiate", "service", "allocate", "supply", "barter"):
        eligibility = owner_rules.agreement_eligibility(
            authority=npc["authority"],
            feasible=npc["stock"] >= npc["minimum_retained"],
            constraints=[True]
            if npc["vital_constraints_known"] and npc["vital_constraints_satisfied"]
            else [None]
            if not npc["vital_constraints_known"]
            else [False],
        )
        if eligibility != "eligible":
            blocker = eligibility
    if op == "trade" or (op == "service" and spec.get("parameters", {}).get("pay_on_acceptance")):
        if hero["gold"] < npc["agreed_price"]:
            blocker = "insufficient_money"
    if op in ("sell", "refund") and npc["gold"] < npc["agreed_price"]:
        blocker = "insufficient_counterparty_money"
    if op in CRAFT_OPS:
        required = set(spec.get("parameters", {}).get("required_traits", ["workable_material"]))
        if not required <= set(obj["properties"].get("traits", [])):
            blocker = "unsupported_capability"
        requested_caps = set(spec.get("parameters", {}).get("result_capabilities", []))
        if not requested_caps <= possible_capabilities(before):
            blocker = "unsupported_capability"
        if state["objects"]["material"]["quantity"] < 1:
            blocker = "insufficient_material"
        if state["objects"]["tool"]["durability"] <= 0:
            blocker = "unusable_tool"
        if not set(spec.get("parameters", {}).get("required_tool_capabilities", [])) <= set(
            state["objects"]["tool"]["capabilities"]
        ):
            blocker = "missing_tool_capability"
    if blocker:
        result.update(
            outcome="clarification_required"
            if blocker in ("target_not_selected", "clarification_required")
            else "goal_unreachable",
            goal_reachable=None
            if blocker in ("target_not_selected", "clarification_required")
            else False,
            blocker=blocker,
        )
        return state, result, None
    dc = 10 if op in ("test", "practice", "stabilize") else 15
    if world["weather"] == "rain" and op in CRAFT_OPS | {"movement", "disarm"}:
        dc += 2
    effect = spec.get("parameters", {}).get(
        "effect", {"heal": "heal", "dead_heal": "heal", "illusion": "illusion"}.get(op, "light")
    )
    effect_spec = state["facts"]["effect_registry"].get(effect, {})
    mana_cost = effect_spec.get("mp_cost", 0) if op in MAGIC_OPS - {"dismiss"} else 0
    st_cost = 2 if op in CRAFT_OPS | {"movement", "attack", "disarm", "practice"} else 0
    if op == "overcast" and state["facts"].get("overcast_payment_choice") not in (
        "hp",
        "exhaustion",
    ):
        result.update(
            outcome="clarification_required", goal_reachable=None, blocker="payment_choice_required"
        )
        return state, result, None
    if op == "stabilize":
        owner_rules.stabilize(owner_rules.Life(**state["target_life"]))
    if op == "overcast":
        # Explicitly documented HP choice; no model-selected payment. The pure
        # function enforces full price and records the attempted expenditure.
        paid, payment = owner_rules.overcast(
            owner_rules.Life(**hero["life"]),
            hero["mp"],
            mana_cost,
            state["facts"]["overcast_payment_choice"],
        )
        result["overcast"] = payment
        dc = payment["dc"]
    else:
        paid = None
    if mana_cost and op != "overcast" and hero["mp"] < mana_cost:
        result.update(outcome="goal_unreachable", goal_reachable=False, blocker="insufficient_mp")
        return state, result, None
    if hero["st"] < st_cost:
        result.update(outcome="goal_unreachable", goal_reachable=False, blocker="insufficient_st")
        return state, result, None
    rng = Random(seed)
    if op in ROLL_OPS or (
        op == "observe" and spec.get("parameters", {}).get("observation_uncertain")
    ):
        natural = rng.randint(1, 20)
        modifier = ability_modifier(
            hero["abilities"][
                spec["task"]
                if spec["task"] in hero["abilities"]
                else {
                    "repair": "intelligence",
                    "smithing": "intelligence",
                    "arcana": "intelligence",
                    "medicine": "wisdom",
                    "athletics": "strength",
                    "acrobatics": "dexterity",
                    "persuasion": "charisma",
                    "melee": "strength",
                    "survival": "wisdom",
                }[spec["task"]]
            ]
        )
        rolled = owner_rules.check(
            natural,
            modifier,
            dc,
            exhaustion=hero["life"]["exhaustion"],
            partial=op
            not in (
                "attack",
                "stabilize",
                "overcast",
                "negotiate",
                "service",
                "allocate",
                "supply",
                "barter",
            ),
        )
        if op == "attack" and natural == 1:
            rolled.update(succeeded=False, outcome="failure")
        result.update(d20_required=True, roll=rolled, outcome=rolled["outcome"])
        text_key = (
            "success"
            if rolled["succeeded"]
            else "partial"
            if rolled["outcome"] == "partial_success"
            else "failure"
        )
        if rolled["complication"]:
            world["minute"] += 1
    success = text_key == "success"
    partial = text_key == "partial"
    hero["st"] -= st_cost
    if op == "overcast":
        hero["life"] = asdict(paid)
        hero["mp"] = 0
    elif op == "scroll":
        obj["quantity"] = 0
    else:
        hero["mp"] -= mana_cost
    if op == "dead_heal":
        result.update(outcome="no_effect_dead_target", goal_reachable=False)
    if op in CRAFT_OPS:
        state["objects"]["material"]["quantity"] -= 1
        wear = 2 if result.get("roll") and result["roll"]["complication"] else 1
        state["objects"]["tool"]["durability"] = max(
            0, state["objects"]["tool"]["durability"] - wear
        )
        obj["durability"] = min(
            obj["maximum"], obj["durability"] + (4 if success else 1 if partial else -1)
        )
        if op in ("craft", "shape", "join", "separate", "restore"):
            obj["name"] = (
                spec["goal"]
                if success
                else "незавершённая заготовка"
                if partial
                else "повреждённые материалы"
            )
            obj["properties"]["capabilities"] = (
                spec.get("parameters", {}).get("result_capabilities", []) if success else []
            )
            if "dependent" in state["objects"]:
                state["objects"]["dependent"]["functional"] = False
        if spec.get("parameters", {}).get("consumed_component"):
            state["objects"]["component"]["quantity"] = 0
        if not success and not partial:
            state["facts"]["work_fatigue"] = True
    elif op in ("take", "transfer"):
        obj["holder"] = "hero" if op == "take" else state["facts"]["transfer_destination"]
        if op == "transfer" and state["facts"]["transfer_title"]:
            obj["legal_owner"] = obj["holder"]
    elif op in ("trade", "sell", "refund", "barter") and success:
        price = npc["agreed_price"]
        if op == "trade":
            hero["gold"] -= price
            npc["gold"] += price
            obj["holder"] = "hero"
            obj["legal_owner"] = "hero"
            npc["stock"] -= 1
        elif op in ("sell", "refund"):
            hero["gold"] += price
            npc["gold"] -= price
            obj["holder"] = "counterparty"
            obj["legal_owner"] = "counterparty"
            npc["stock"] += 1
        else:
            obj.update(holder="counterparty", legal_owner="counterparty")
            state["objects"]["barter_item"].update(holder="hero", legal_owner="hero")
    elif op in ("negotiate", "service", "allocate", "supply") and success:
        npc["agreement"] = True
        npc["accepted_terms"] = deepcopy(npc["offer_terms"])
        if spec.get("parameters", {}).get("pay_on_acceptance"):
            hero["gold"] -= npc["agreed_price"]
            npc["gold"] += npc["agreed_price"]
        if spec.get("parameters", {}).get("give_tool_on_acceptance"):
            state["objects"]["tool"]["holder"] = npc["id"]
        if spec.get("parameters", {}).get("pledge_tool_on_acceptance"):
            state["objects"]["tool"]["pledged"] = True
        if op == "allocate":
            state["facts"]["allocation"] = {"civilians": 58, "garrison": 42}
            world["food"] -= 100
        elif op == "supply":
            world["treasury"] -= world["supplier_price"]
            npc["gold"] += world["supplier_price"]
            world["supplier_stock"] -= 20
            world["food"] += 20
    elif op in ("move", "movement"):
        if success or (partial and spec.get("parameters", {}).get("partial_completes_move")):
            if spec.get("parameters", {}).get("movement_changes_place", True):
                hero["place"] = state["route"]["destination"]
            state["facts"]["movement_completed"] = True
            state["facts"].update(
                spec.get("parameters", {}).get("partial_conditions", {}) if partial else {}
            )
        elif not partial:
            hero["life"] = asdict(owner_rules.damage(owner_rules.Life(**hero["life"]), 1))
    elif op == "attack" and success:
        dice = [rng.randint(1, 4) for _ in range(2 if result["roll"]["natural"] == 20 else 1)]
        result["damage_dice"] = dice
        result["damage"] = sum(dice)
        state["target_life"] = asdict(
            owner_rules.damage(owner_rules.Life(**state["target_life"]), sum(dice))
        )
    elif op == "disarm":
        if success:
            state["objects"]["target_weapon"]["holder"] = hero["place"]
        elif partial:
            state["facts"]["weakened_grip"] = True
    elif op == "defend":
        hero["st"] -= 1
        state["facts"]["dodge_remaining_attacks"] = 1
    elif op == "stabilize" and success:
        state["target_life"] = asdict(
            owner_rules.stabilize(owner_rules.Life(**state["target_life"]))
        )
    elif op in ("cast", "scroll", "sustain") or (op == "overcast" and success):
        state["facts"]["supported_effect_active"] = True
        state["facts"]["effect_expires_at"] = world["minute"] + 10
    elif op in ("heal", "heal_item"):
        state["target_life"] = asdict(owner_rules.heal(owner_rules.Life(**state["target_life"]), 3))
        if op == "heal_item":
            obj["quantity"] = 0
    elif op == "capability" and success:
        state["facts"]["capability_applied"] = spec["parameters"]["required_capability"]
    elif op == "illusion" and success:
        state["facts"]["illusion_visible"] = True
    elif op == "dismiss":
        if state["facts"].get("supported_effect_owner") != "hero":
            raise ValueError("Only an explicitly owned effect can be dismissed")
        state["facts"]["supported_effect_active"] = False
    elif op in ("rest", "recover"):
        hero["st"] = min(hero["st_cap"], hero["st"] + 3)
    elif op == "long_rest":
        hero["life"] = asdict(owner_rules.long_rest(owner_rules.Life(**hero["life"])))
        hero["mp"], hero["st"] = hero["mp_cap"], hero["st_cap"]
    elif op == "unequip":
        state["facts"]["subject_equipped"] = False
    elif op == "choose":
        hero["talents"] = [state["facts"]["allowed_talents"][0]]
        # Resilient is an existing supported talent: maximum HP grows, current HP is not healed.
        hero["life"]["maximum"] += 2
        state["facts"]["available_talent_choices"] = 0
    elif op in (
        "inform",
        "observe",
        "compare",
        "verify",
        "record",
        "practice",
        "test",
        "deploy",
        "disarm",
        "defend",
        "cast",
        "sustain",
    ):
        if spec.get("parameters", {}).get("test_damage"):
            obj["durability"] = max(0, obj["durability"] - spec["parameters"]["test_damage"])
        state["facts"]["recorded_result"] = {
            "operation": op,
            "subject": obj["id"],
            "confirmed": success,
            "partial": partial,
        }
    duration = (
        0
        if op in ("noop", "verify", "compare", "clarify")
        else 30
        if op in CRAFT_OPS | {"practice"}
        else 480
        if op == "long_rest"
        else 10
        if op == "rest"
        else state["route"]["minutes"]
        if op in ("move", "movement")
        else spec.get("parameters", {}).get("wait_minutes", 1)
        if op == "wait"
        else 1
    )
    world["minute"] += duration
    result["duration_minutes"] = world["minute"] - before["world"]["minute"]
    return state, result, text_key


def changes(before, after, prefix=""):
    output = []
    for key in sorted(before.keys() | after.keys()):
        path = prefix + key
        a, b = before.get(key), after.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            output.extend(changes(a, b, path + "."))
        elif a != b:
            output.append({"field": path, "before": a, "after": b})
    return output


def narrate(before, after, result, spec, text_key):
    if text_key is None:
        return {
            "closed_container": (
                f"{spec['subject'].capitalize()} находится в закрытом контейнере. "
                "Прямого доступа нет; "
                "предмет не переместился; для доступа нужен допустимый способ открытия."
            ),
            "target_not_selected": (
                f"Нужно уточнить конкретную цель: {spec['subject']}. "
                "До выбора предметы, ресурсы и положение не изменились."
            ),
            "unsupported_capability": spec["failure"]
            + " Высокий бросок не добавит отсутствующего свойства; "
            "расхода маны, новых вещей и урона нет.",
            "unknown_effect": (
                "В объявленном реестре героя подходящий эффект не изучен. Назови "
                "существующую доступную способность или предмет, который его даёт; "
                "бросок не создаёт новое умение."
            ),
            "clarification_required": (
                "Полномочия и жизненно важные ограничения NPC известны не полностью. "
                "Сначала нужно уточнить эти условия; соглашения и передачи ресурсов "
                "ещё нет."
            ),
            "outside_authority_or_vital_limits": (
                "Предложение выходит за подтверждённые полномочия или жизненно "
                "важные ограничения NPC. Высокий бросок не снимает эти границы; "
                "передачи ресурсов нет."
            ),
            "payment_choice_required": (
                "Нужно явно выбрать оплату здоровьем или истощением. "
                "До выбора броска и расхода нет."
            ),
            "insufficient_material": (
                "Материала для выбранной работы не хватает. Попытка не создаёт недостающие части."
            ),
            "insufficient_money": (
                "Имеющихся монет для этой цены не хватает. Оплаты и передачи нет."
            ),
            "insufficient_counterparty_money": (
                "У второй стороны не хватает монет. Передачи товара и оплаты нет."
            ),
            "unusable_tool": (
                "Объявленный инструмент непригоден для работы. "
                "Нужен допустимый способ выполнить её имеющимися средствами."
            ),
            "missing_tool_capability": (
                "Имеющийся инструмент не поддерживает нужный способ обработки. "
                "Сначала нужен подходящий доступный инструмент; броска и расхода нет."
            ),
            "insufficient_mp": (
                "На известный эффект сейчас не хватает маны. Эффект не возник и "
                "ресурс не списан; перерасход требует отдельного явного выбора цены."
            ),
            "insufficient_st": (
                "Для полного действия не хватает текущего запаса сил. Попытка не "
                "дала заявленного результата; отрицательных ST и бесплатного успеха "
                "нет."
            ),
        }[result["blocker"]]
    text = spec[text_key].format(arrows=before["hero"]["arrows"])
    parts = [text]
    roll = result["roll"]
    if roll:
        parts.append(
            f"Проверка: {roll['natural']} на D20, итог {roll['total']} при сложности {roll['dc']}."
        )
    delta = result["changes"]
    amounts = []
    for key, label in [
        ("hero.gold", "монет"),
        ("hero.mp", "MP"),
        ("hero.st", "ST"),
        ("hero.life.hp", "HP"),
    ]:
        d = next((r for r in delta if r["field"] == key), None)
        if d:
            amounts.append(f"{label}: {d['before']} → {d['after']}")
    if amounts:
        parts.append("; ".join(amounts) + ".")
    elif result["operation"] in CRAFT_OPS:
        parts.append(
            "Расход материала и износ инструмента сохранены; исходные вещи не дублируются."
        )
    elif result.get("duration_minutes", 0) >= 5:
        parts.append(f"Прошло {result['duration_minutes']} мин.")
    if after["hero"]["life"]["hp"] == 0 and before["hero"]["life"]["hp"] > 0:
        parts.append("Здоровье опустилось до0HP: ты теряешь сознание.")
    if roll and roll["complication"]:
        parts.append("Натуральная1 добавила потерю темпа; лишняя минута учтена в мире.")
    return " ".join(parts)


def clean_prose(text):
    text = re.sub(r"(?<=[А-Яа-яЁё])(?=[0-9])", " ", text)
    return re.sub(r"([0-9])(HP|MP|ST)\b", r"\1 \2", text)


def compile_row(source, spec):
    state = initial(source, spec)
    seed = seed_for(source["id"])
    after, result, text_key = resolve(state, spec, seed)
    result["changes"] = changes(state, after)
    result["before_sha256"] = digest(state)
    result["after_sha256"] = digest(after)
    answer = clean_prose(narrate(state, after, result, spec, text_key))
    return {
        "schema_version": SCHEMA,
        "sample_id": source["id"],
        "campaign_id": source["id"].rsplit("_", 2)[0] + "_" + source["id"].rsplit("_", 1)[1],
        "scene_mode": "grounded_narration",
        "synthetic": True,
        "human_reviewed": False,
        "source_scenario": source,
        "spec": spec,
        "seed": seed,
        "public_context": {"source_context": source["context"], "state": state},
        "player_message": source["action"],
        "engine_receipt": result,
        "assistant_reply": answer,
        "after_state": after,
        "review": {
            "method": "CURATED_INTENT_CONTROLLED_REALIZATION_AND_REFERENCE_REPLAY",
            "human_approval": False,
        },
    }


def build(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    definitions = specs()
    rows = []
    for source in rows_v2():
        family, variant, index = source["id"].rsplit("_", 2)
        spec = definitions[source["family"] + ":" + index]
        rows.append(compile_row(source, spec))
    from training.rule_curriculum import KINDS
    from training.rule_curriculum import rows as rule_rows

    rows.extend(rule_rows())
    edge_order = sorted(KINDS, key=lambda key: hashlib.sha256(key.encode()).hexdigest())
    edge_parts = {
        kind: ("test" if n < 2 else "val" if n < 4 else "train")
        for n, kind in enumerate(edge_order)
    }
    splits = {s: [] for s in ("train", "val", "test")}
    for row in rows:
        if row["sample_id"].startswith("edge_"):
            splits[edge_parts[row["engine_receipt"]["boundary_kind"]]].append(row)
            continue
        index = int(row["sample_id"].rsplit("_", 1)[1])
        split = "train" if index < 8 else "val" if index == 8 else "test"
        splits[split].append(row)
    for name, values in splits.items():
        (output / (name + ".jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in values), encoding="utf-8"
        )
    manifest = {
        "schema": SCHEMA,
        "dataset_policy": POLICY,
        "status": "CANDIDATE_REQUIRES_AUDIT",
        "samples": len(rows),
        "source_scenarios": 1000,
        "additional_rule_boundaries": 100,
        "sha256": digest(sorted(rows, key=lambda r: r["sample_id"])),
        "file_sha256": {
            s: hashlib.sha256((output / (s + ".jsonl")).read_bytes()).hexdigest() for s in splits
        },
        "splits": {s: len(v) for s, v in splits.items()},
        "human_reviewed_samples": 0,
        "real_game_episodes": 0,
        "reference_executions": len(rows),
        "curated_intents": len(definitions),
        "reference_execution_kind": "SYNTHETIC_REFERENCE_NOT_LIVE_GAME_REPLAY",
        "parameters_file_sha256": hashlib.sha256(
            (SPEC_FILE.parent / "parameters-v4.json").read_bytes()
        ).hexdigest(),
        "training_steps": 0,
        "outcomes": dict(Counter(r["engine_receipt"]["outcome"] for r in rows)),
        "spec_file_sha256": hashlib.sha256(SPEC_FILE.read_bytes()).hexdigest(),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(build(a.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
