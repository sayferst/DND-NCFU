"""Owner policy is opt-in, replayable, and acts on real canonical entities."""

import json
from dataclasses import replace

import pytest
from test_adventure import world_value

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.catalog_engine import Engine, execute
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.domain.owner_rules_runtime import change_hp, life
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.unified_session import UnifiedSession, context


def campaign(*, policy=1, hp=0, seed=11):
    s = UnifiedSession.create(
        Character(), "cleric", "healer", seed=seed, catalog_revision=3, owner_rules_policy=policy
    )
    raw = world_value()
    raw["definitions"].append(
        {
            "id": "wounded_type",
            "name": "Раненый путник",
            "kind": "actor",
            "categories": ["npcs"],
            "properties": {"class": "guard", "hp_max": 12},
        }
    )
    raw["entities"].append(
        {
            "id": "wounded",
            "definition_id": "wounded_type",
            "parent_id": "pier",
            "state": {"hp": hp, "life": "unconscious" if not hp else "alive"},
        }
    )
    s.start_world(build_world(raw, s, "owner-rules-fixture"))
    return s


def test_stabilize_preserves_zero_hp_and_full_replay():
    s = campaign()
    # Retry is an ordinary attempt; both success and failure remain in the log.
    for i in range(10):
        s.perform_gameplay("stabilize", {"target": "wounded"}, f"aid-{i}")
        if s.gameplay.get("owner_life", {}).get("wounded", {}).get("stable"):
            break
    assert s.gameplay["owner_life"]["wounded"]["stable"]
    assert next(e for e in s.catalog.entities if e.id == "wounded").state["hp"] == 0
    assert receipt(s)["owner_rules"]["version"] == "owner-rules-1"
    restored = Session.from_dict(s.to_dict(), version=31)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == s.dice.checkpoint()


def test_old_origin_does_not_gain_new_rules_and_invalid_policy_rejected():
    s = campaign(policy=0, hp=3)
    assert "owner_rules_policy" not in s.to_dict()["unified"]["origin"]
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
    with pytest.raises(ValueError):
        UnifiedSession.create(
            Character(), "mage", "focus", catalog_revision=1, owner_rules_policy=1
        )


def test_real_hp_accessor_never_resurrects_dead_and_keeps_death_counters():
    s = campaign(hp=1)
    e = Engine(s.gameplay, context(s), DiceRoller(10), {})
    change_hp(e, "wounded", -1)
    assert life(e, "wounded").hp == 0 and not life(e, "wounded").stable
    change_hp(e, "wounded", -1, critical=True)
    assert life(e, "wounded").failures == 2
    change_hp(e, "wounded", -1)
    assert life(e, "wounded").dead
    change_hp(e, "wounded", 10)
    assert life(e, "wounded").dead and e.hp("wounded") == 0


def test_overcast_reaches_zero_and_price_survives_failure():
    # An explicitly authored engine fixture, not represented as a played-save episode.
    s = UnifiedSession.create(
        Character(), "mage", "focus", seed=8, catalog_revision=3, owner_rules_policy=1
    )
    raw = s.gameplay.copy()
    raw["mp"] = 0
    c = context(s)
    c["world"] = c["world"] | {"hp": 2}
    result = execute(
        raw, "overcast", {"spell": "light", "payment": "hp", "target": "hero"}, c, DiceRoller(1)
    )
    assert result["world"]["hp"] == 0 and result["state"]["mp"] == 0
    payment = next(r for r in result["battle_events"] if r["kind"] == "owner_overcast")
    assert payment["hp_spent"] == 2 and payment["missing_mp"] == 1
    assert not payment["succeeded"]
    assert result["state"]["owner_life"]["hero"]["failures"] == 0


def test_insufficient_hp_or_implicit_payment_cannot_cast():
    s = UnifiedSession.create(
        Character(), "mage", "focus", seed=8, catalog_revision=3, owner_rules_policy=1
    )
    raw = s.gameplay.copy()
    raw["mp"] = 0
    c = context(s)
    c["world"] = c["world"] | {"hp": 1}
    for payment in ("hp", None):
        dice = DiceRoller(3)
        checkpoint = dice.checkpoint()
        with pytest.raises(ValueError):
            execute(
                raw, "overcast", {"spell": "light", "payment": payment, "target": "hero"}, c, dice
            )
        assert dice.checkpoint() == checkpoint


def test_activation_copy_logs_policy_without_rewriting_old_origin(tmp_path):
    from training.enable_attempts_copy import activate

    s = campaign(policy=0, hp=5)
    source = tmp_path / "old.json"
    source.write_text(json.dumps({"schema_version": 31, "session": s.to_dict()}))
    old = source.read_bytes()
    copied = activate(source, tmp_path / "new.json", owner_rules=True)
    assert source.read_bytes() == old
    assert copied.gameplay["owner_rules_policy"] == 1
    assert "owner_rules_policy" not in copied.to_dict()["unified"]["origin"]
    assert Session.from_dict(copied.to_dict(), version=31).to_dict() == copied.to_dict()


def test_stable_zero_hp_recovers_after_recorded_hours_without_resurrection():
    from rpg_vkr.domain.catalog_actions_v2 import advance
    from rpg_vkr.domain.owner_rules import stabilize
    from rpg_vkr.domain.owner_rules_runtime import apply

    s = campaign()
    e = Engine(s.gameplay, context(s), DiceRoller(3), {})
    apply(e, "wounded", stabilize(life(e, "wounded")))
    at = e.state["owner_recovery"]["wounded"]
    assert 60 <= at - e.state["minute"] <= 240
    advance(e, at - e.state["minute"])
    assert life(e, "wounded").hp >= 1
    assert "wounded" not in e.state["owner_recovery"]


def test_healer_spends_actual_turn_and_mana_to_help_fallen_living_ally():
    from rpg_vkr.domain.owner_rules_runtime import assist_fallen

    s = campaign()
    e = Engine(s.gameplay, context(s), DiceRoller(3), {})
    id = "wounded"
    definition = replace(
        e.definitions[e.actors[id].definition_id], properties={"behavior": "healer", "hp_max": 12}
    )
    # Explicit unit fixture, never presented as an actual campaign receipt.
    change_hp(e, id, 6)
    change_hp(e, "hero", -e.hp("hero"))
    battle = {"order": ["hero", id], "sides": {"hero": "party", id: "party"}}
    assert assist_fallen(e, id, definition, battle)
    assert e.hp("hero") > 0 and (e.actors[id].state or {})["mp"] == 9
    change_hp(e, "hero", -100)
    assert not assist_fallen(e, id, definition, battle)
    assert life(e).dead


def test_public_agreement_terms_required_before_rng_and_success_binds():
    from test_free_actions_pipeline import campaign as food_campaign

    from rpg_vkr.domain.food_negotiation import disclose_terms
    from rpg_vkr.domain.food_negotiation import execute as negotiate

    s = food_campaign(guard=True)
    e = Engine(s.gameplay | {"owner_rules_policy": 1}, context(s), DiceRoller(3), {})
    for resident in e.state["living_world"]["residents"].values():
        resident["food"] = 0
    e.state["living_world"]["stocks"][e.scene.current]["food"] = 100
    checkpoint = e.dice.checkpoint()
    with pytest.raises(ValueError, match="CLARIFICATION_REQUIRED"):
        negotiate(e, {"policy": "balanced"})
    assert e.dice.checkpoint() == checkpoint
    disclose_terms(e)
    e.check = lambda task, dc: True  # Isolate agreement eligibility from roll sampling.
    before = e.state["living_world"]["stocks"][e.scene.current]["food"]
    negotiate(e, {"policy": "balanced"})
    record = e.events[-1]
    assert record["accepted"]
    assert before - record["food_after"] == sum(record["transfers"].values())


def test_rest_benefits_once_per_day_and_no_benefits_after_damage():
    from rpg_vkr.domain.owner_rules_runtime import finish_rest

    s = campaign(hp=12)
    s.perform_gameplay("rest", {}, "rest1")
    with pytest.raises(ValueError, match="24"):
        s.perform_gameplay("rest", {}, "rest2")
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
    e = Engine(s.gameplay, context(s), DiceRoller(5), {})
    e.owner_rest_pending = True
    change_hp(e, "hero", -1)
    before = e.hp("hero")
    finish_rest(e)
    assert e.hp("hero") == before and e.events[-1]["completed"] is False


def test_planner_exposes_owner_commands_only_after_activation():
    from rpg_vkr.narrative.catalog_protocol import planning_context, validate_proposal

    value = {"command": "overcast", "args": {"spell": "light", "payment": "hp"}}
    plan = {"check": "none", "steps": []}
    for policy in (0, 1):
        s = campaign(policy=policy, hp=12)
        state = {"catalog_actions": planning_context(s)}
        if policy:
            assert validate_proposal(value, plan, state) == value
        else:
            with pytest.raises(ValueError):
                validate_proposal(value, plan, state)


def test_melee_hit_at_zero_is_critical_and_flags_do_not_leak_to_other_damage():
    from rpg_vkr.domain.catalog_actions_v2 import hit

    s = campaign()
    e = Engine(s.gameplay, context(s), DiceRoller(1), {"target": "wounded"})
    e.char = replace(e.char, strength=18)
    e.state["weapon"] = ""
    hit(e, "hero", "wounded")
    assert life(e, "wounded").failures == 2
    assert not getattr(e, "owner_hit_flags", {})
    # An unrelated later damage source must not inherit critical/nonlethal flags.
    e.damage("hero", e.hp("hero"))
    e.damage("hero", 1)
    assert life(e).failures == 1


def test_new_composition_works_with_owner_policy_and_replays_real_inventory():
    from random import Random

    from test_attempt_generalization import attempt, configured

    seed = next(n for n in range(1000) if Random(n).randint(1, 20) == 20)
    s = configured(seed=seed)
    s.perform_gameplay("enable_owner_rules", {"version": 1}, "activate")
    knife = next(i["id"] for i in s.gameplay["items"] if i.get("kind") == "dagger")
    attempt(s, "transform", "spear", ["pole"], knife)
    assert next(i for i in s.gameplay["items"] if i["id"] == "pole")["form"] == "spear"
    event = next(
        e for e in s.turns[-1].gameplay["result"]["battle_events"] if e["kind"] == "owner_check"
    )
    assert event["task"] == "athletics" and event["natural"] == 20
    assert event["total"] < 30  # The true total is not forged into a success threshold.
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
