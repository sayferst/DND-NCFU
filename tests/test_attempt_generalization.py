"""Held-out combinations use identical primitives, including adversarial plans."""

from copy import deepcopy

import pytest
from test_free_actions_pipeline import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.receipts import receipt


def configured(*, seed=5):
    with content.using(3):
        armour = next(r for r in content.available("armour") if r["material"] == "mat_0_0")
    definitions, entities = [], []
    for id, name, props, condition in (
        ("pole", "Ясеневое древко", {"affordances": ["shaft", "wood", "rigid"]}, 12),
        ("ribbon", "Льняная лента", {"affordances": ["fabric", "binding", "cord"]}, 8),
        ("scrap", "Железная заготовка", {"game_template_id": "mat_0_0"}, 20),
        ("equipment", "Ремонтные инструменты", {"game_template_id": "house_0_0"}, 20),
        ("damaged", "Сломанная пластинчатая броня", {"game_template_id": armour["id"]}, 1),
        # A magical-sounding name cannot grant mechanical flight.
        ("fake", "Посох всесильного полёта", {"affordances": ["rigid"]}, 12),
    ):
        definitions.append(
            {
                "id": "type_" + id,
                "name": name,
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"portable": True, **props},
            }
        )
        entities.append(
            {
                "id": id,
                "definition_id": "type_" + id,
                "parent_id": "hero",
                "owner_id": "hero",
                "state": {"condition": condition},
            }
        )
    return campaign(seed=seed, extra_definitions=definitions, extra_entities=entities)


def attempt(s, operation, goal, items, tool="", **extra):
    return s.perform_gameplay(
        "attempt",
        {
            "version": 1,
            "plan": {
                "operation": operation,
                "goal": goal,
                "items": items,
                "tool": tool,
                **extra,
            },
        },
        s._request_token(),
    )


def test_unseen_wooden_spear_uses_same_transformation_and_real_combat():
    s = configured()
    knife = next(i["id"] for i in s.gameplay["items"] if i.get("kind") == "dagger")
    attempt(s, "transform", "spear", ["pole"], knife)
    product = next(i for i in s.gameplay["items"] if i["id"] == "pole")
    assert product["form"] == "spear" and product["kind"] == "weapon"
    assert product["durability"] == 6 and product["usage_penalty"] == -1
    s.perform_gameplay("equip", {"item": "pole"}, "equip-new")
    s.perform_gameplay("travel", {"destination": "path"}, "road-new")
    s.perform_gameplay("encounter", {"enemies": ["watcher"]}, "battle-new")
    s.perform_gameplay("attack", {"target": "watcher"}, "attack-new")
    assert next(i for i in s.gameplay["items"] if i["id"] == "pole")["durability"] == 5
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_new_two_input_splint_consumes_sources_without_second_items():
    s = configured()
    knife = next(i["id"] for i in s.gameplay["items"] if i.get("kind") == "dagger")
    attempt(s, "transform", "splint", ["pole", "ribbon"], knife)
    assert not any(i["id"] == "ribbon" for i in s.gameplay["items"])
    assert not any(e.id == "ribbon" for e in s.catalog.entities)
    assert next(i for i in s.gameplay["items"] if i["id"] == "pole")["form"] == "splint"
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_repair_damaged_armour_consumes_real_compatible_material():
    s = configured()
    attempt(s, "repair", "", ["damaged"], "equipment")
    assert next(i for i in s.gameplay["items"] if i["id"] == "damaged")["durability"] > 1
    assert not any(i["id"] == "scrap" for i in s.gameplay["items"])
    assert next(i for i in s.gameplay["items"] if i["id"] == "equipment")["durability"] < 20
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_ordinary_object_can_be_used_for_support_without_new_recipe():
    s = configured()
    before = s.dice.checkpoint()
    s.submit("Использую ясеневое древко как опору")
    assert receipt(s)["free_attempt"]["mode"] == "AUTO_SUCCESS"
    assert s.gameplay["physical_uses"][-1]["affordance"] == "support"
    assert next(i for i in s.gameplay["items"] if i["id"] == "pole")["deployed"]
    assert not any(t.id == "pole" for t in s.interaction_state().carried())
    assert next(e for e in s.catalog.entities if e.id == "pole").parent_id == s.current_place_id
    assert before == s.dice.checkpoint()


def test_high_roll_cannot_supply_missing_material_traits_or_name_granted_magic():
    s = configured()
    knife = next(i["id"] for i in s.gameplay["items"] if i.get("kind") == "dagger")
    before = s.dice.checkpoint()
    attempt(s, "transform", "fishing_gear", ["pole"], knife)
    assert receipt(s)["free_attempt"]["mode"] == "ATTEMPT_WITHOUT_TARGET_SUCCESS"
    assert s.dice.checkpoint() == before
    attempt(s, "use", "flight", ["fake"])
    assert receipt(s)["free_attempt"]["outcome"] == "target_unreachable"
    assert s.dice.checkpoint() == before


@pytest.mark.parametrize("change", ["stats", "fake_id", "same_tool", "unknown_effect"])
def test_adversarial_model_plan_is_rejected_atomically(change):
    s = configured()
    before = s.to_dict(), s.dice.checkpoint()
    plan = {"operation": "transform", "goal": "spear", "items": ["pole"], "tool": "equipment"}
    if change == "stats":
        plan["damage"] = 999
    elif change == "fake_id":
        plan["items"] = ["nonexistent"]
    elif change == "same_tool":
        plan["tool"] = "pole"
    else:
        plan["goal"] = "infinite_gold"
    with pytest.raises(ValueError):
        s.perform_gameplay("attempt", {"version": 1, "plan": plan}, "invalid")
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_language_model_proposal_does_not_bypass_closed_plan_schema():
    from rpg_vkr.narrative.catalog_protocol import planning_context, validate_proposal

    s = configured()
    state = {"catalog_actions": planning_context(s)}
    plan = {"steps": [], "check": "none"}
    bad = {
        "command": "attempt",
        "args": {
            "version": 1,
            "plan": {"operation": "mint", "goal": "gold", "items": [], "tool": ""},
        },
    }
    with pytest.raises(ValueError):
        validate_proposal(bad, plan, state)
    assert "spear" in state["catalog_actions"]["attempt_plans"]["forms"]
    assert Session.from_dict(deepcopy(s.to_dict()), version=31).to_dict() == s.to_dict()
