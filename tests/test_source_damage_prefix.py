"""Modern type-before-amount damage uses the same finite engine packets."""

import pytest

from rpg_vkr.world_library.creature_actions import damage_components


@pytest.mark.parametrize("label", ["Дробящий", "Колющий", "Рубящий"])
def test_physical_prefix_is_equivalent_to_legacy_damage(label):
    assert damage_components(f"{label} урон 9 (2к6 + 2).") == (
        [{"dice": "2d6+2", "element": "physical"}],
        True,
    )


def test_mixed_prefix_damage_preserves_order_and_dice():
    assert damage_components("Колющий урон 7 (1к8 + 3) плюс урон огнём 7 (2к6).") == (
        [{"dice": "1d8+3", "element": "physical"}, {"dice": "2d6", "element": "fire"}],
        True,
    )


@pytest.mark.parametrize(
    "tail", [" если цель лежит", " или 12 рубящего урона", ", и цель схвачена"]
)
def test_conditions_alternatives_and_riders_are_not_discarded(tail):
    assert not damage_components("Рубящий урон 4 (1к4 + 2)" + tail)[1]
