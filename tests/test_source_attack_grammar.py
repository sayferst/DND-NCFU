"""New source grammar, constant damage and immutable published V3 programs."""

from dataclasses import replace

import pytest
from test_library_creature_actions import engine_with_actions

from rpg_vkr.domain.catalog_actions_v2 import hit
from rpg_vkr.world_library.creature_actions import extract, validate
from rpg_vkr.world_library.model import digest, schemas
from rpg_vkr.world_library.source_extract import save_effect


@pytest.mark.parametrize("damage", ["1", "1 (1к1)"])
@pytest.mark.parametrize("natural", [15, 20])
@pytest.mark.parametrize("choice", [None, 0])
def test_modern_constant_attack_never_rolls_zero_dice_or_doubles_the_constant(
    monkeypatch, damage, natural, choice
):
    rules = extract(
        {
            "действия": [
                {
                    "название": "Клюв",
                    "описание": (
                        "Бросок рукопашной атаки: +8, досягаемость 5 футов. "
                        f"Попадание: {damage} колющего урона."
                    ),
                }
            ]
        }
    )
    validate(rules)
    assert rules["actions"][0]["complete"]
    assert rules["actions"][0]["dice"] == "0d4+1"
    engine, properties = engine_with_actions()
    old = engine.definitions["wounded_type"]
    engine.definitions[old.id] = replace(
        old,
        properties=properties
        | {
            "source_actions_v2": rules,
            "source_attack_math_version": 2,
            "damage_dice": "0d4+1",
            "attack_bonus": 8,
        },
    )
    calls = []

    def roll(expression, reason):
        calls.append(expression)
        assert expression == "1d20"
        return natural

    monkeypatch.setattr(engine, "roll", roll)
    before = engine.world.hp
    hit(engine, "wounded", "hero", source_attack=choice)
    assert engine.world.hp == before - 1 and calls == ["1d20"]


def test_modern_ranged_mixed_attack_and_conditional_tail():
    raw = {
        "действия": [
            {
                "название": "Луч",
                "описание": (
                    "Бросок дальнобойной атаки: +7, дистанция 60/120 футов. "
                    "Попадание: 4 (1к4 + 2) урона огнём и 2 урона холодом."
                ),
            }
        ]
    }
    row = extract(raw)["actions"][0]
    assert row["ranged"] and row["complete"] and row["bonus"] == 7
    assert row["components"] == [
        {"dice": "1d4+2", "element": "fire"},
        {"dice": "0d4+2", "element": "cold"},
    ]
    raw["действия"][0]["описание"] += " Если цель мокрая, она падает."
    assert not extract(raw)["actions"][0]["complete"]


def test_published_v3_schema_does_not_accept_an_unversioned_constant_effect():
    assert digest(schemas()["source_features_v3"]) == (
        "ead94a5628520609d0e03ab3ce3c402a99e3849fa1622dcad4c15f53c50e2dec"
    )
    assert (
        save_effect(
            "Цель должна совершить спасбросок Телосложения Сл 12. "
            "При провале она получает 5 урона ядом и становится отравленной на 1 минуту."
        )
        is None
    )


def test_modern_save_colon_preserves_actual_damage_and_difficulty():
    effect = save_effect(
        "Спасбросок Ловкости: Сл 14. При провале цель получает 7 (2к6) урона огнём, "
        "при успехе — половину урона."
    )
    assert effect["dc"] == 14 and effect["ability"] == "dexterity" and effect["half"]
    assert effect["components"] == [{"dice": "2d6", "element": "fire"}]
