"""Source features must use canonical HP, death rules, RNG and rollback."""

from dataclasses import replace

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.creature_rules import (
    VERSION,
    after_attack,
    before_turn,
    incoming,
    validate_runtime,
)


def properties():
    return {
        "library_rules_version": VERSION,
        "attack_bonus": 3,
        "damage_dice": "1d4",
        "source_resistances": ["fire"],
        "source_immunities": ["poison"],
        "source_vulnerabilities": ["cold"],
        "source_extra_attacks": 2,
        "source_regeneration": 3,
    }


def test_source_damage_rules_use_same_canonical_life():
    session = campaign(hp=12)
    engine = Engine(session.gameplay, context(session), session.dice, {})
    old = engine.definitions["wounded_type"]
    p = properties()
    engine.definitions["wounded_type"] = replace(old, properties=old.properties | p)
    checkpoint = engine.dice.checkpoint()
    assert engine.damage("wounded", 9, "fire") == 4
    assert engine.hp("wounded") == 8
    assert engine.damage("wounded", 50, "poison") == 0
    before_turn(engine, "wounded", p)
    assert engine.hp("wounded") == 11
    assert engine.dice.checkpoint() == checkpoint
    assert engine.events[-1]["kind"] == "source_regeneration"
    engine.damage("wounded", 6, "cold")
    assert engine.hp("wounded") == 0
    before_turn(engine, "wounded", p)
    assert engine.hp("wounded") == 0  # No resurrection by a passive callback.


def test_extra_attacks_stop_when_target_falls_and_have_a_budget(monkeypatch):
    from rpg_vkr.domain import catalog_actions_v2

    class EngineFacade:
        hits = 0

        def hp(self, id):
            return 0 if id == "target" and self.hits else 5

    e = EngineFacade()

    def hit(engine, attacker, target):
        assert attacker == "source" and target == "target"
        engine.hits += 1

    monkeypatch.setattr(catalog_actions_v2, "hit", hit)
    after_attack(e, "source", "target", properties())
    assert e.hits == 1
    with pytest.raises(ValueError):
        validate_runtime(properties() | {"source_extra_attacks": 3})
    with pytest.raises(ValueError):
        incoming(properties() | {"source_immunities": ["execute_sql"]}, 5, "fire")


def test_source_resistance_rounding_and_immunity_precedence():
    p = properties()
    assert incoming(p, 9, "fire") == 4
    assert incoming(p, 9, "cold") == 18
    assert incoming(p, 9, "poison") == 0
    assert incoming(p, 9, "physical") == 9


def test_all_compiled_creatures_have_bounded_executable_stats():
    from rpg_vkr.world_library.creature_rules import compile_creature
    from rpg_vkr.world_library.model import ROOT, read_jsonl

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    for row in rows:
        props = compile_creature(row)
        validate_runtime(props)
        assert props["hp_max"] > 0
        assert props["armour_class"] > 0
