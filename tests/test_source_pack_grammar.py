"""Equivalent standard pack wording must preserve the exact ally and target conditions."""

import pytest

from rpg_vkr.world_library.creature_actions import extract as attacks
from rpg_vkr.world_library.source_extract import extract, literal_pack_tactics

BODY = (
    "Страж совершает с преимуществом броски атаки по существу, если как минимум "
    "один союзник стража находится в пределах 5 футов от этого существа, "
    "и этот союзник дееспособен."
)


@pytest.mark.parametrize(
    "body",
    [
        BODY,
        BODY.replace(", и этот", " и этот"),
        "Страж совершает атаку против существа с преимуществом если хотя бы один из союзников "
        "стража находится в пределах 5 футов от существа и союзник дееспособен.",
        "Страж имеет преимущество на броске атаки против существа, если хотя бы один из союзников "
        "стража находится в пределах 5 футов от существа и союзник не выведен из строя.",
        "Страж получает преимущество на броски атаки против существ, "
        "если хотя бы один из союзников "
        "стража находится в пределах 5 футов от цели атаки и боеспособен.",
    ],
)
def test_standard_equivalent_pack_wording_compiles_to_the_existing_closed_operation(body):
    raw = {"черты": [{"название": "Тактика стаи", "описание": body}]}
    program = extract(raw, attacks(raw))
    assert program["pack_tactics"] and "Тактика стаи" in program["supported_names"]


@pytest.mark.parametrize(
    "change",
    [
        ("5 футов", "10 футов"),
        ("от этого существа", "от самого стража"),
        ("дееспособен", "не дееспособен"),
        ("броски атаки", "броски атаки оружием"),
        ("дееспособен.", "дееспособен. Кроме того, он восстанавливает 2 HP."),
        ("совершает с", "не совершает с"),
    ],
)
def test_extra_conditions_and_different_radius_are_not_silently_accepted(change):
    assert not literal_pack_tactics(BODY.replace(*change).casefold())
