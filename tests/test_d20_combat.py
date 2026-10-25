"""New resolver arithmetic and replay, independent of legacy combat records."""

from dataclasses import replace

import pytest

from rpg_vkr.domain.d20_combat import Combatant, armour_class, resolve_attack
from rpg_vkr.domain.dice import DiceRoller


def fighter(id="hero"):
    return Combatant(id, 30, 30, 16, 12, "sword", 1)


@pytest.mark.parametrize(
    "armour,expected",
    [("none", 12), ("leather", 13), ("reinforced_leather", 14), ("mail", 16), ("plate", 18)],
)
def test_ac_has_one_formula_and_shield_is_removed(armour, expected):
    assert armour_class(14, armour) == expected
    assert armour_class(14, armour, True) == expected + 2
    assert armour_class(8) == 9


def test_same_parameters_have_identical_rules_for_hero_and_npc():
    a, b = fighter(), fighter("npc")
    for seed in range(1000):
        forward = resolve_attack(a, b, DiceRoller(seed))
        backward = resolve_attack(b, a, DiceRoller(seed))
        assert (forward.hit, forward.damage, forward.critical) == (
            backward.hit,
            backward.damage,
            backward.critical,
        )


def test_replay_and_advantage_cancellation():
    a, b = fighter(), fighter("npc")
    dice = DiceRoller(42)
    before = dice.checkpoint()
    result = resolve_attack(a, b, dice, advantage=True)
    assert result.selected_roll == max(result.hit_rolls)
    dice.restore(before)
    assert resolve_attack(a, b, dice, advantage=True) == result
    assert resolve_attack(a, b, DiceRoller(42), advantage=True, disadvantage=True) == (
        resolve_attack(a, b, DiceRoller(42))
    )


def test_miss_critical_and_nonlethal_are_distinct():
    a, b = fighter(), replace(fighter("npc"), hp=1)
    outcomes = [resolve_attack(a, b, DiceRoller(seed)) for seed in range(100)]
    for result in outcomes:
        if result.selected_roll == 1:
            assert not result.hit and result.damage == 0 and result.hp_after == 1
        if result.critical:
            assert len(result.damage_roll.individual_rolls) == 2
        assert not result.killed
    assert any(r.critical for r in outcomes)
    assert any(r.defeated for r in outcomes)
    lethal = resolve_attack(a, b, DiceRoller(5), lethal=True)
    assert lethal.killed == lethal.defeated


def test_invalid_action_does_not_consume_rng():
    dice = DiceRoller(42)
    before = dice.checkpoint()
    with pytest.raises(ValueError):
        resolve_attack(fighter(), fighter(), dice)
    assert dice.checkpoint() == before
    with pytest.raises(ValueError):
        replace(fighter(), weapon="greatsword", shield=True)
