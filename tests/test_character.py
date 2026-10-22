"""Independent expected values from the SRD 5.2.1 ability table (pp. 5–6)."""

from dataclasses import asdict

import pytest

from rpg_vkr.domain.character import Character, ability_modifier, resolve_ability_check


@pytest.mark.parametrize(
    ("score", "expected"),
    [(1, -5), (8, -1), (9, -1), (10, 0), (11, 0), (12, 1), (14, 2), (15, 2), (20, 5), (30, 10)],
)
def test_modifier_matches_reference_table(score, expected):
    assert ability_modifier(score) == expected


@pytest.mark.parametrize("score", [0, 31, True, 10.0, "14"])
def test_invalid_ability_score_is_rejected(score):
    with pytest.raises(ValueError):
        ability_modifier(score)


@pytest.mark.parametrize(
    ("score", "die", "difficulty", "total", "success"),
    [
        (14, 8, 10, 10, True),
        (14, 7, 10, 9, False),
        (8, 10, 10, 9, False),
        (30, 1, 10, 11, True),
        (1, 20, 20, 15, False),
    ],
)
def test_check_uses_total_and_no_automatic_one_or_twenty(score, die, difficulty, total, success):
    result = resolve_ability_check("strength", score, die, difficulty)
    assert result.total == total
    assert result.succeeded is success


@pytest.mark.parametrize("die", [0, 21, True])
def test_invalid_d20_is_rejected(die):
    with pytest.raises(ValueError):
        resolve_ability_check("strength", 14, die, 10)


def test_character_validation_and_round_trip():
    hero = Character(name="Мира", strength=18, charisma=13)
    assert Character.from_dict(asdict(hero)) == hero
    for changes in [{"strength": False}, {"name": " "}, {"strength": 31}, {"unexpected": 1}]:
        with pytest.raises(ValueError):
            Character.from_dict(asdict(hero) | changes)
