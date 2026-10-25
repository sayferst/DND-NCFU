"""Deterministic dice checks, not a claim of statistical certification."""

from rpg_vkr.domain.dice import DiceRoller


def test_known_seed_records_each_actual_roll():
    roller = DiceRoller(seed=42)
    rolls = [roller.roll_d20() for _ in range(5)]
    assert [roll.value for roll in rolls] == [4, 1, 9, 8, 8]
    assert [roll.index for roll in rolls] == [1, 2, 3, 4, 5]


def test_d20_range_includes_both_endpoints():
    roller = DiceRoller(seed=42)
    values = [roller.roll_d20().value for _ in range(2000)]
    assert all(type(value) is int and 1 <= value <= 20 for value in values)
    assert set(values) == set(range(1, 21))


def test_independent_generators_replay_the_same_seed():
    first = DiceRoller(seed=42)
    second = DiceRoller(seed=42)
    assert first.roll_d20().value == 4
    assert first.roll_d20().value == 1
    assert second.roll_d20().value == 4
    assert second.roll_d20().value == 1
