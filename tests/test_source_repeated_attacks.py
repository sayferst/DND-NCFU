"""Unnamed repeated attacks preserve attack type and reject ambiguous source choices."""

import pytest

from rpg_vkr.world_library.source_extract import source_sequence


@pytest.mark.parametrize("ranged,word", [(False, "рукопашные"), (True, "дальнобойные")])
def test_unique_matching_attack_repeats_without_using_the_other_type(ranged, word):
    actions = [
        {"name": "Основной удар", "ranged": ranged, "complete": True},
        {"name": "Другой удар", "ranged": not ranged, "complete": True},
    ]
    assert source_sequence(f"Страж совершает три {word} атаки.", actions) == [0, 0, 0]


@pytest.mark.parametrize("complete", [True, False])
def test_ambiguous_attack_type_never_chooses_one_arbitrarily(complete):
    actions = [
        {"name": "Меч", "ranged": False, "complete": True},
        {"name": "Коготь", "ranged": False, "complete": complete},
    ]
    assert not source_sequence("Страж совершает две рукопашные атаки.", actions)


def test_incomplete_unique_attack_and_additional_clauses_stay_pending():
    actions = [{"name": "Удар", "ranged": False, "complete": False}]
    assert not source_sequence("Страж совершает две рукопашные атаки.", actions)
    actions[0]["complete"] = True
    assert not source_sequence(
        "Страж совершает две рукопашные атаки. Он может телепортироваться.", actions
    )
