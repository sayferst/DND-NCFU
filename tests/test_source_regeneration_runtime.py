"""Conditional source healing, real damage suppression and source-specific death timing."""

from dataclasses import replace

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.owner_rules_runtime import life
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.damage_packets import apply as packet
from rpg_vkr.world_library.regeneration_rules import (
    VERSION,
    advance,
    extract,
    pending_zero,
    start_turn,
    state,
    validate,
)


def rules(*, zero=True, minimum=0):
    return {
        "version": VERSION,
        "amount": 5,
        "minimum_hp": minimum,
        "suppress_elements": ["acid", "fire"],
        "zero_death": zero,
        "supported_names": ["Регенерация"],
    }


def engine(program=None, *, policy=1, hp=12):
    s = campaign(hp=hp, policy=policy)
    e = Engine(s.gameplay, context(s), s.dice, {})
    d = e.definitions["wounded_type"]
    e.definitions[d.id] = replace(
        d,
        properties=d.properties
        | {
            "hp_max": 20,
            "library_regeneration_rules": program or rules(),
        },
    )
    return e


def test_exact_clause_extraction_rejects_environment_material_and_extra_rules():
    body = (
        "Тролль восстанавливает 10 хитов в начале своего хода. "
        "Если тролль получает урон кислотой или огнём, эта особенность не действует "
        "в начале следующего хода тролля. Тролль умирает только если начинает свой "
        "ход с 0 хитов и не может регенерировать."
    )
    raw = {"черты": [{"название": "Регенерация", "описание": body}]}
    p = extract(raw)
    validate(p)
    assert p["amount"] == 10 and p["zero_death"] and p["minimum_hp"] == 0
    assert p["suppress_elements"] == ["acid", "fire"]
    for suffix in (" Если он на солнце, он не лечится.", " Он также отращивает голову."):
        raw["черты"][0]["описание"] = body + suffix
        assert extract(raw) is None
    raw["черты"][0]["описание"] = body.replace("урон кислотой или огнём", "рубящий урон")
    assert extract(raw) is None


def test_minimum_one_hp_and_invalid_program_guards():
    p = extract(
        {
            "черты": [
                {
                    "название": "Регенерация",
                    "описание": "Червь восстанавливает по 10 хитов в начале каждого своего хода, "
                    "если у него остался хотя бы 1 хит.",
                }
            ]
        }
    )
    assert p["minimum_hp"] == 1 and not p["zero_death"]
    for bad in (
        rules(zero=True, minimum=1),
        rules() | {"amount": True},
        rules() | {"suppress_elements": ["fire", "fire"]},
    ):
        with pytest.raises(ValueError):
            validate(bad)


@pytest.mark.parametrize("policy", [0, 1])
def test_element_disables_only_next_start_and_no_rolls_are_consumed(policy):
    e = engine(policy=policy)
    rng = e.dice.checkpoint()
    e.damage("wounded", 4, "physical")
    e.damage("wounded", 1, "fire")
    assert e.hp("wounded") == 7 and state(e, "wounded")["suppressed"]
    start_turn(e, "wounded")
    assert e.hp("wounded") == 7 and not state(e, "wounded")["suppressed"]
    start_turn(e, "wounded")
    assert e.hp("wounded") == 12 and e.dice.checkpoint() == rng


def test_reduced_packet_only_suppresses_when_element_deals_positive_damage():
    e = engine()
    e.status("wounded", "shield", 3, 2)
    packet(e, "wounded", [(3, "fire"), (2, "physical")], "hero")
    assert not state(e, "wounded")["suppressed"]
    packet(e, "wounded", [(1, "physical"), (1, "fire")], "hero")
    assert state(e, "wounded")["suppressed"]
    assert len([r for r in e.events if r["kind"] == "source_regeneration_suppressed"]) == 1


@pytest.mark.parametrize("policy", [0, 1])
def test_zero_hp_regenerates_before_death_save_without_resurrecting_the_dead(policy):
    e = engine(policy=policy)
    e.damage("wounded", 100, "physical")
    assert e.hp("wounded") == 0 and pending_zero(e, "wounded")
    if policy:
        assert not life(e, "wounded").dead
    start_turn(e, "wounded")
    assert e.hp("wounded") == 5 and not pending_zero(e, "wounded")
    e.damage("wounded", 100, "fire")
    assert e.hp("wounded") == 0 and pending_zero(e, "wounded")
    start_turn(e, "wounded")
    assert not pending_zero(e, "wounded")
    assert (e.actors["wounded"].state or {})["life"] == "dead"
    e.change_hp("wounded", 20)
    start_turn(e, "wounded")
    assert e.hp("wounded") == 0


def test_other_actor_and_one_hp_minimum_keep_native_r01_death_rules():
    e = engine(rules(zero=False, minimum=1))
    e.damage("wounded", 100)
    assert life(e, "wounded").dead
    start_turn(e, "wounded")
    assert life(e, "wounded").dead and e.hp("wounded") == 0
    e = engine(rules(zero=False, minimum=1), hp=2)
    e.damage("wounded", 2)
    start_turn(e, "wounded")
    assert e.hp("wounded") == 0 and not life(e, "wounded").dead


def test_unconditional_healing_at_zero_does_not_grant_source_death_deferral():
    e = engine(rules(zero=False, minimum=0))
    e.damage("wounded", 12)
    assert pending_zero(e, "wounded") and not life(e, "wounded").dead
    start_turn(e, "wounded")
    assert e.hp("wounded") == 5
    e.damage("wounded", 100)
    assert life(e, "wounded").dead and not pending_zero(e, "wounded")


def test_regeneration_never_overrides_death_from_six_exhaustion_levels():
    from rpg_vkr.domain.owner_rules import add_exhaustion
    from rpg_vkr.domain.owner_rules_runtime import apply

    e = engine()
    apply(e, "wounded", add_exhaustion(life(e, "wounded"), 6))
    start_turn(e, "wounded")
    assert life(e, "wounded").dead and e.hp("wounded") == 0


def test_out_of_combat_elapsed_healing_is_bounded_and_does_not_change_rng():
    e = engine(hp=1)
    rng = e.dice.checkpoint()
    advance(e, e.state["minute"], e.state["minute"] + 1440)
    assert e.hp("wounded") == 20 and e.dice.checkpoint() == rng
    events = len(e.events)
    advance(e, e.state["minute"], e.state["minute"] + 1440)
    assert len(e.events) == events  # Full-HP passive actors do not flood long-action receipts.


@pytest.mark.parametrize("policy", [0, 1])
@pytest.mark.parametrize("suppressed", [False, True])
def test_real_npc_round_resolves_regeneration_before_zero_hp_and_battle_completion(
    monkeypatch, policy, suppressed
):
    from rpg_vkr.domain.catalog_actions_v2 import npc_round

    e = engine(policy=policy)
    e.state["battle"] = {
        "order": ["hero", "wounded"],
        "initiative": {"hero": 20, "wounded": 10},
        "sides": {"hero": "party", "wounded": "enemy"},
        "round": 1,
    }
    e.damage("wounded", 100, "fire" if suppressed else "physical")
    called = []

    def roll(expression, reason):
        assert "Спасбросок смерти" not in reason
        called.append(expression)
        return 2

    monkeypatch.setattr(e, "roll", roll)
    npc_round(e, "recover")
    if suppressed:
        assert (e.actors["wounded"].state or {})["life"] == "dead"
        assert e.state["battle"] is None and not called
    else:
        assert e.hp("wounded") == 5 and e.state["battle"]


def test_registered_source_program_survives_real_encounter_and_full_session_replay(tmp_path):
    from rpg_vkr.application import Session
    from rpg_vkr.world_library.bridge import commit, preview
    from rpg_vkr.world_library.model import ROOT, read_jsonl
    from rpg_vkr.world_library.store import Library

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    row = next(r for r in rows if r["id"] == "rpg_b001a3c17939219dc0e6f750")
    library = Library.sqlite(tmp_path / "regeneration-library.sqlite3")
    try:
        library.migrate()
        library.import_records([row])
        s = campaign(hp=12, seed=17)
        proposal = preview(library, s, row["id"], "source_vegepygmy")
        proposal = replace(
            proposal,
            entities=tuple(replace(e, state=dict(e.state or {}, hp=1)) for e in proposal.entities),
        )
        commit(s, proposal)
        s.perform_gameplay("encounter", {"enemies": ["source_vegepygmy"]}, "regeneration-encounter")
        if s.gameplay.get("battle") and s.world.hp > 0:
            s.perform_gameplay("recover", {}, "regeneration-own-turn")
        restored = Session.from_dict(s.to_dict(), version=31)
        assert restored.to_dict() == s.to_dict()
        assert restored.dice.checkpoint() == s.dice.checkpoint()
        source = next(e for e in s.catalog.entities if e.id == "source_vegepygmy")
        assert source.state.get("library_regeneration", {}).get("version") == 1
    finally:
        library.close()


def test_incapacitation_prevents_action_but_not_passive_start_of_turn_healing():
    from test_source_rules_runtime import engine_with_rules

    from rpg_vkr.world_library import source_runtime

    e, _ = engine_with_rules()
    d = e.definitions["wounded_type"]
    e.definitions[d.id] = replace(
        d, properties=d.properties | {"library_regeneration_rules": rules()}
    )
    e.damage("wounded", 10)
    source_runtime.apply_condition(e, "wounded", "paralyzed", "hero", 10)
    rng = e.dice.checkpoint()
    assert list(source_runtime.turn_order(e, ["wounded"])) == []
    assert e.hp("wounded") == 7 and e.dice.checkpoint() == rng


def test_master_card_explains_the_executable_regeneration_rule():
    from rpg_vkr.world_library.model import ROOT, read_jsonl
    from rpg_vkr.world_library.presentation import card

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    row = next(r for r in rows if r["id"] == "rpg_b001a3c17939219dc0e6f750")
    value = card(row)
    summary = next(text for label, text in value["facts"] if label == "Регенерация")
    assert "+3 HP" in summary and "огонь" in summary and "при 0 HP" in summary
