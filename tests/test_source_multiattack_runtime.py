"""Conditional source multiattacks execute only their declared hit triggers."""

from dataclasses import replace

import pytest
from test_source_rules_runtime import engine_with_rules

from rpg_vkr.world_library import source_runtime
from rpg_vkr.world_library.creature_actions import extract as attacks
from rpg_vkr.world_library.multiattack_rules import extract, validate
from rpg_vkr.world_library.source_extract import extract as features


def raw():
    return {
        "действия": [
            {
                "название": "Мультиатака",
                "описание": "Грик совершает две атаки: одну хвостом, и одну щупальцами. "
                "Если грик попадает щупальцами, он может совершить одну атаку клювом "
                "по той же самой цели.",
            },
            *[
                {
                    "название": n,
                    "описание": "Рукопашная атака оружием: +5 к попаданию, "
                    "досягаемость 5 футов. Попадание: 0 колющего урона.",
                }
                for n in ["Хвост", "Щупальца", "Клюв"]
            ],
        ]
    }


def test_conditional_program_references_the_exact_base_and_followup():
    stat = raw()
    a = attacks(stat)
    f = features(stat, a)
    program = extract(stat, a, f)
    assert program == {
        "version": "library-multiattack-1",
        "choices": [[0, 1]],
        "followups": [{"after": 1, "attack": 2}],
    }
    validate(program, a["actions"], f)


@pytest.mark.parametrize("hit", [True, False])
def test_real_attack_results_control_followup_even_when_damage_is_zero(monkeypatch, hit):
    stat = raw()
    e, f = engine_with_rules(stat)
    definition = e.definitions["wounded_type"]
    program = extract(stat, attacks(stat), f)
    properties = definition.properties | {
        "library_multiattack_rules": program,
        "source_attack_math_version": 2,
    }
    e.definitions[definition.id] = replace(definition, properties=properties)
    monkeypatch.setattr(e, "roll", lambda formula, label: 20 if hit else 1)
    source_runtime.turn(e, "wounded", "hero", properties)
    assert len(e.attacks) == (3 if hit else 2)
    assert all(a["hit"] == hit for a in e.attacks)
    assert all(a["damage"] == 0 for a in e.attacks)


def test_unknown_additional_clause_is_not_declared_complete():
    stat = raw()
    stat["действия"][0]["описание"] += " Кроме того, цель телепортируется."
    a = attacks(stat)
    assert extract(stat, a, features(stat, a)) is None


def test_alternative_sequence_uses_reachable_attack_and_preserves_all_its_attacks(monkeypatch):
    stat = raw()
    stat["действия"][0]["описание"] = "Страж совершает две атаки Хвостом или Клювом."
    stat["действия"] = [stat["действия"][0], stat["действия"][1], stat["действия"][3]]
    stat["действия"][2]["описание"] = (
        "Дальнобойная атака оружием: +5 к попаданию, дистанция 30 футов. "
        "Попадание: 0 колющего урона."
    )
    e, f = engine_with_rules(stat)
    definition = e.definitions["wounded_type"]
    program = extract(stat, attacks(stat), f)
    assert program["choices"] == [[0, 0], [1, 1]]
    properties = definition.properties | {
        "library_multiattack_rules": program,
        "source_attack_math_version": 2,
    }
    e.definitions[definition.id] = replace(definition, properties=properties)
    e.state["source_rules_v3"]["positions"]["wounded"]["point"] = [30, 0, 0]
    monkeypatch.setattr(e, "roll", lambda formula, label: 20)
    source_runtime.turn(e, "wounded", "hero", properties)
    assert len(e.attacks) == 2
    choices = [r["action_index"] for r in e.events if r["kind"] == "source_attack_choice"]
    assert choices == [1, 1]


@pytest.mark.parametrize("duplicate", [False, True])
def test_two_same_or_one_each_is_an_explicit_complete_choice(duplicate):
    stat = raw()
    stat["действия"][0]["описание"] = (
        "Аартук совершает или две атаки Хвостом, или две атаки Клювом, "
        "или по одной каждой " + ("каждой " if duplicate else "") + "из них."
    )
    stat["действия"] = [stat["действия"][0], stat["действия"][1], stat["действия"][3]]
    a = attacks(stat)
    p = extract(stat, a, features(stat, a))
    assert p["choices"] == [[0, 0], [1, 1], [0, 1]]
    validate(p, a["actions"], features(stat, a))
