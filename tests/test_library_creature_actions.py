"""Actual attack choices, exact mixed sequences and version-preserving engine replay."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog_actions_v2 import hit
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.creature_actions import VERSION, extract, selected, turn, validate
from rpg_vkr.world_library.creature_rules import compile_creature
from rpg_vkr.world_library.model import ROOT, read_jsonl


def source_actions():
    return extract(
        {
            "действия": [
                {
                    "название": "Укус",
                    "описание": (
                        "Рукопашная атака оружием: +5 к попаданию, досягаемость 5 фт., одна цель. "
                        "Попадание: 7 (1к6 + 4) колющего урона."
                    ),
                },
                {
                    "название": "Когти",
                    "описание": (
                        "Рукопашная атака оружием: +4 к попаданию, одна цель. "
                        "Попадание: 5 (1к4 + 3) рубящего урона."
                    ),
                },
                {
                    "название": "Мультиатака",
                    "описание": ("Существо совершает три атаки: одну укусом и две когтями."),
                },
            ]
        }
    )


def engine_with_actions():
    session = campaign(hp=12)
    engine = Engine(session.gameplay, context(session), session.dice, {})
    old = engine.definitions["wounded_type"]
    rules = source_actions()
    properties = old.properties | {
        "library_rules_version": VERSION,
        "source_actions_v2": rules,
        "attack_bonus": 5,
        "damage_dice": "1d6+4",
    }
    engine.definitions["wounded_type"] = replace(old, properties=properties)
    return engine, properties


def test_exact_source_sequence_and_ambiguous_substitution_rejection():
    rules = source_actions()
    assert rules["multiattack"] == [0, 1, 1] and rules["multiattack_complete"]
    validate(rules)
    from rpg_vkr.world_library.creature_actions import parse_multiattack

    for prose in (
        "Совершает три атаки: одну укусом или три когтями.",
        "Если ранен, совершает три атаки: одну укусом и две когтями.",
        "Совершает три атаки: одну укусом и одну когтями.",
    ):
        assert parse_multiattack(prose.casefold(), rules["actions"]) == []
    broken = deepcopy(rules)
    broken["multiattack"] = [25]
    with pytest.raises(ValueError):
        validate(broken)


def test_riders_stay_partial_while_mixed_damage_has_exact_components():
    rules = extract(
        {
            "действия": [
                {
                    "название": "Укол",
                    "описание": (
                        "+5 к попаданию. Попадание: 7 (1к6 + 4) колющего урона. "
                        "Цель должна совершить спасбросок Телосложения."
                    ),
                },
                {
                    "название": "Огненный клинок",
                    "описание": (
                        "+5 к попаданию. Попадание: 7 (1к6 + 4) рубящего урона "
                        "и 3 (1к6) урона огнём."
                    ),
                },
            ]
        }
    )
    assert len(rules["actions"]) == 2
    assert not rules["actions"][0]["complete"]
    assert rules["actions"][1]["complete"]
    assert rules["actions"][1]["components"] == [
        {"dice": "1d6+4", "element": "physical"},
        {"dice": "1d6", "element": "fire"},
    ]
    with pytest.raises(ValueError, match="handler"):
        selected({"source_actions_v2": rules}, 0)


def test_mixed_packet_is_one_hit_for_zero_hp_and_death_counters():
    from rpg_vkr.domain.owner_rules_runtime import life
    from rpg_vkr.world_library.damage_packets import apply

    engine, _ = engine_with_actions()
    engine.damage("hero", engine.hp("hero") - 5)
    assert apply(engine, "hero", [(3, "physical"), (3, "fire")], "wounded") == 5
    assert life(engine).hp == 0 and life(engine).failures == 0
    engine.owner_hit_flags = {"critical": True}
    apply(engine, "hero", [(1, "physical"), (1, "fire")], "wounded")
    assert life(engine).failures == 2 and not life(engine).dead


def test_mixed_packet_applies_each_resistance_before_one_hp_change():
    from rpg_vkr.world_library.damage_packets import apply

    engine, properties = engine_with_actions()
    old = engine.definitions["wounded_type"]
    engine.definitions[old.id] = replace(
        old, properties=properties | {"source_resistances": ["fire"]}
    )
    assert apply(engine, "wounded", [(2, "physical"), (9, "fire")], "hero") == 6
    assert engine.hp("wounded") == 6


def test_critical_doubles_dice_but_not_flat_modifier(monkeypatch):
    engine, _ = engine_with_actions()
    rolls = iter([20, 2, 3])
    expressions = []

    def roll(expression, reason):
        expressions.append(expression)
        return next(rolls)

    monkeypatch.setattr(engine, "roll", roll)
    before = engine.world.hp
    hit(engine, "wounded", "hero", source_attack=0)
    assert expressions == ["1d20", "1d6", "1d6"]
    assert engine.world.hp == before - 9  # (2 + 3 + 4), no doubled +4.
    assert engine.attacks[-1]["damage"] == 9
    assert engine.events[0]["kind"] == "source_attack_choice"


def test_sequence_stops_when_target_drops_and_no_extra_death_failures(monkeypatch):
    engine, properties = engine_with_actions()
    engine.damage("hero", engine.hp("hero") - 5)
    rolls = iter([20, 6, 6])
    monkeypatch.setattr(engine, "roll", lambda expression, reason: next(rolls))
    turn(engine, "wounded", "hero", properties)
    assert engine.world.hp == 0 and len(engine.attacks) == 1
    from rpg_vkr.domain.owner_rules_runtime import life

    assert life(engine).failures == 0


def test_source_choices_do_not_accept_bool_indices_or_hero_override():
    engine, properties = engine_with_actions()
    checkpoint = engine.dice.checkpoint()
    for index in (True, -1, 30):
        with pytest.raises(ValueError):
            selected(properties, index)
    with pytest.raises(ValueError):
        hit(engine, "hero", "wounded", source_attack=0)
    assert engine.dice.checkpoint() == checkpoint


def test_every_source_action_model_and_definition_fit_engine_bounds():
    from rpg_vkr.domain.catalog import Definition

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    assert len(rows) == 3920
    for row in rows:
        rules = row["attributes"]["actions_v2"]
        validate(rules)
        properties = compile_creature(row)
        Definition(row["id"], row["name"], "actor", ("creatures",), properties)
    assert sum(r["attributes"]["actions_v2"]["multiattack_complete"] for r in rows) >= 96


def test_real_registered_mixed_sequence_replays_without_global_library(tmp_path):
    from rpg_vkr.world_library.bridge import commit, preview
    from rpg_vkr.world_library.store import Library

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    row = next(r for r in rows if len(set(r["attributes"]["actions_v2"]["multiattack"])) > 1)
    library = Library.sqlite(tmp_path / "library.sqlite3")
    try:
        library.migrate()
        library.import_records([row])
        session = campaign(hp=12)
        before = session.to_dict()
        proposal = preview(library, session, row["id"], "source_mixed")
        assert session.to_dict() == before
        commit(session, proposal)
        session.perform_gameplay("encounter", {"enemies": ["source_mixed"]}, "source-mixed")
        restored = Session.from_dict(session.to_dict(), version=31)
        assert restored.to_dict() == session.to_dict()
        assert restored.dice.checkpoint() == session.dice.checkpoint()
    finally:
        library.close()
