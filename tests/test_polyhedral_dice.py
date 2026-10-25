"""Safe dice expressions and reproducible checkpoints, including old d20 stream."""

import pytest

from rpg_vkr.domain.dice import DiceRoller


@pytest.mark.parametrize("sides", [4, 6, 8, 10, 12, 20, 100])
def test_ranges_and_replay(sides):
    roller = DiceRoller(42)
    before = roller.checkpoint()
    result = roller.roll(f"5d{sides}-3")
    assert all(1 <= n <= sides for n in result.individual_rolls)
    assert result.total == sum(result.individual_rolls) - 3
    assert result.rng_counter == 5
    roller.restore(before)
    assert roller.roll(f"5d{sides}-3") == result


@pytest.mark.parametrize(
    "expression", ["0d20", "101d6", "d0", "2d7", "d20+10001", "__import__('os')", "d20" * 30]
)
def test_invalid_input_does_not_consume_randomness(expression):
    roller = DiceRoller(42)
    before = roller.checkpoint()
    with pytest.raises(ValueError):
        roller.roll(expression)
    assert roller.checkpoint() == before


def test_new_d20_and_old_d20_use_same_seeded_stream():
    old, new = DiceRoller(42), DiceRoller(42)
    for _ in range(1000):
        assert old.roll_d20().value == new.roll("d20").total
    assert old.checkpoint() == new.checkpoint()
