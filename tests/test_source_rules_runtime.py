"""Source saves, finite powers, condition math, geometry, timing and old replay."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library import source_runtime as runtime
from rpg_vkr.world_library.creature_actions import extract as attacks
from rpg_vkr.world_library.model import ROOT, dump, read_jsonl
from rpg_vkr.world_library.source_extract import extract, validate
from rpg_vkr.world_library.source_geometry import contains, move, positions


def stat():
    return {
        "характеристики": {"сил": 14, "лов": 12, "тел": 16, "инт": 10, "муд": 12, "хар": 8},
        "спасброски": {"тел": 5},
        "скорость": "30 футов",
        "особенности": [
            {
                "название": "Сопротивление магии",
                "описание": (
                    "Существо имеет преимущество на спасброски от заклинаний "
                    "и других магических эффектов."
                ),
            },
            {
                "название": "Легендарное сопротивление (2/день)",
                "описание": (
                    "Если существо проваливает спасбросок, оно может сделать его успешным."
                ),
            },
        ],
        "действия": [
            {
                "название": "Коготь",
                "описание": (
                    "Рукопашная атака оружием: +5 к попаданию, досягаемость 5 футов, одна цель. "
                    "Попадание: 2 (1к4) рубящего урона."
                ),
            }
        ],
    }


def engine_with_rules(raw=None, policy=1):
    raw = raw or stat()
    old_actions = attacks(raw)
    program = extract(raw, old_actions)
    session = campaign(hp=12, policy=policy)
    e = Engine(session.gameplay, context(session), session.dice, {})
    old = e.definitions["wounded_type"]
    properties = old.properties | {
        "library_rules_version": runtime.VERSION,
        "source_actions_v2": old_actions,
        "source_features_v3": program,
        "attack_bonus": 5,
        "damage_dice": "1d4",
    }
    e.definitions[old.id] = replace(old, properties=properties)
    runtime.initialize(e)
    positions(e)["wounded"]["point"] = [5, 0, 0]
    positions(e)["hero"]["point"] = [0, 0, 0]
    return e, program


def test_magic_resistance_rolls_two_and_daily_budget_is_not_midnight_reset(monkeypatch):
    e, program = engine_with_rules()
    assert program["magic_resistance"] and program["legendary_resistance"] == 2
    values = iter([2, 18])
    monkeypatch.setattr(e, "roll", lambda expression, reason: next(values))
    assert runtime.saving_throw(e, "wounded", "constitution", 14, magical=True)
    assert e.events[-1]["total"] == 23 and not e.events[-1]["legendary"]
    monkeypatch.setattr(e, "roll", lambda expression, reason: 2)
    assert runtime.saving_throw(e, "wounded", "constitution", 30)
    assert runtime.saving_throw(e, "wounded", "constitution", 30)
    e.state["minute"] += 1440
    assert not runtime.saving_throw(e, "wounded", "constitution", 30)
    assert e.state["source_rules_v3"]["spent"]["wounded"]["legendary"] == 2
    e.state["last_battle"] = {"sides": {"hero": "party", "wounded": "party"}}
    runtime.long_rest(e)
    assert runtime.saving_throw(e, "wounded", "constitution", 30)


def test_auto_failed_physical_save_does_not_roll_and_legendary_can_replace_it(monkeypatch):
    e, _ = engine_with_rules()
    runtime.apply_condition(e, "wounded", "paralyzed", "hero", 10)
    monkeypatch.setattr(
        e, "roll", lambda *args: pytest.fail("Automatic save failure must not roll")
    )
    assert runtime.saving_throw(e, "wounded", "dexterity", 15)
    assert e.events[-1]["natural"] is None and e.events[-1]["legendary"]


def test_condition_advantages_cancel_and_rounds_do_not_last_ten_minutes():
    e, _ = engine_with_rules()
    runtime.apply_condition(e, "hero", "poisoned", "wounded", 10)
    assert runtime.attack_mode(e, "hero", "wounded", False) == -1
    runtime.apply_condition(e, "wounded", "blinded", "hero", 10)
    assert runtime.attack_mode(e, "hero", "wounded", False) == 0
    minute = e.state["minute"]
    for _ in range(10):
        runtime.tick(e, "attack", True)
        e.state["minute"] += e.action_minutes
    assert e.state["minute"] == minute + 1
    assert not runtime.conditions(e, "hero")


def test_parry_reaction_is_used_once_and_recovers_on_own_turn():
    raw = stat()
    raw["реакции"] = [
        {
            "название": "Парирование",
            "описание": (
                "Существо добавляет 2 к КД против одной рукопашной атаки, которая должна попасть. "
                "Оно должно видеть атакующего и использовать рукопашное оружие."
            ),
        }
    ]
    e, program = engine_with_rules(raw)
    assert program["parry"] == 2
    assert runtime.parry(e, "wounded", "hero", 12, 12, 12, False) == 14
    assert runtime.parry(e, "wounded", "hero", 12, 12, 12, False) == 12
    runtime.before_actor(e, "wounded")
    assert runtime.parry(e, "wounded", "hero", 20, 25, 12, False) == 12
    assert runtime.parry(e, "wounded", "hero", 12, 12, 12, False) == 14


def test_legendary_actions_have_per_turn_cost_and_cannot_act_on_own_end(monkeypatch):
    raw = stat()
    raw["легендарные_действия_вступление"] = "Существо может совершить 3 легендарных действия."
    raw["легендарные_действия"] = [
        {
            "название": "Атака (стоит 2 действия)",
            "описание": "Существо совершает одну атаку Когтем.",
        }
    ]
    e, program = engine_with_rules(raw)
    assert len(program["legendary"]) == 1
    e.state["battle"] = {
        "order": ["hero", "wounded"],
        "sides": {"hero": "party", "wounded": "enemy"},
    }
    from rpg_vkr.domain import catalog_actions_v2

    calls = []
    monkeypatch.setattr(catalog_actions_v2, "hit", lambda *a, **kw: calls.append(kw))
    runtime.legendary_actions(e, "wounded")
    assert not calls
    runtime.legendary_actions(e, "hero")
    runtime.legendary_actions(e, "hero")
    assert len(calls) == 1
    runtime.before_actor(e, "wounded")
    runtime.legendary_actions(e, "hero")
    assert len(calls) == 2


@pytest.mark.parametrize(
    "shape,point,inside",
    [
        ("cone", [10, 5, 0], True),
        ("cone", [10, 6, 0], False),
        ("cone", [-5, 0, 0], False),
        ("cone", [0, 0, 0], False),
        ("cone", [30, 15, 0], True),
        ("cone", [31, 0, 0], False),
        ("line", [20, 2, 0], True),
        ("line", [20, 3, 0], False),
    ],
)
def test_area_boundaries_without_float_drift(shape, point, inside):
    assert contains(shape, [0, 0, 0], [30, 0, 0], point, 30, 5) is inside


def breath_stat():
    raw = stat()
    raw["действия"].append(
        {
            "название": "Огненное дыхание (перезарядка 5–6)",
            "описание": (
                "Существо выдыхает огонь 15-футовым конусом. Все существа в этой области "
                "должны совершить спасбросок Ловкости Сл 12, получая урон огнём "
                "10 (3к6) при провале или половину этого урона при успехе."
            ),
        }
    )
    return raw


def test_recharge_has_no_roll_when_ready_and_spends_on_attempt(monkeypatch):
    e, program = engine_with_rules(breath_stat())
    assert len(program["powers"]) == 1 and program["powers"][0]["recharge"] == 5
    calls = []

    def roll(expression, reason):
        calls.append(expression)
        return 3

    monkeypatch.setattr(e, "roll", roll)
    runtime.before_actor(e, "wounded")
    assert not calls
    properties = e.definitions["wounded_type"].properties
    runtime.turn(e, "wounded", "hero", properties)
    assert e.state["source_rules_v3"]["spent"]["wounded"]["recharge:0"] == 1
    before = len(calls)
    runtime.before_actor(e, "wounded")
    assert calls[before:] == ["1d6"]
    assert e.state["source_rules_v3"]["spent"]["wounded"]["recharge:0"] == 1
    monkeypatch.setattr(e, "roll", lambda *args: 6)
    runtime.before_actor(e, "wounded")
    assert e.state["source_rules_v3"]["spent"]["wounded"]["recharge:0"] == 0


def test_bad_position_and_invalid_program_are_rejected_before_rng():
    e, program = engine_with_rules()
    checkpoint = e.dice.checkpoint()
    for point in ([True, 0, 0], [10001, 0, 0], [31, 0, 0], [0, 0, 5]):
        with pytest.raises(ValueError):
            move(e, "hero", point, 30)
    program["riders"] = [{"index": 29, "base": [], "effect": {}}]
    with pytest.raises(ValueError):
        validate(program, e.definitions["wounded_type"].properties["source_actions_v2"])
    assert e.dice.checkpoint() == checkpoint


def test_published_v2_battle_replays_with_identical_rng():
    path = ROOT / "tests/fixtures/world-library-source-v2.source.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "b492f726c5132d86184cfd47e56ef6f5932f99e3d8f927b2c8109f566830b8b7"
    )
    fixture = json.loads(path.read_text("utf-8"))
    assert fixture["writer"] == "a7cc7e439e8acdd796c0af4db6bf62d279c0d2d5"
    restored = Session.from_dict(fixture["snapshot"], version=31)
    assert dump(restored.to_dict()) == dump(fixture["snapshot"])
    assert dump(restored.dice.checkpoint()) == dump(fixture["rng"])


def test_all_source_programs_and_pinned_world_payloads_validate():
    from rpg_vkr.domain.catalog import Definition
    from rpg_vkr.world_library.creature_rules import compile_creature

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    assert len(rows) == 3920
    for row in rows:
        validate(row["attributes"]["features_v3"], row["attributes"]["actions_v2"])
        a = row["attributes"]
        properties = compile_creature(row) | {
            "library_id": row["id"],
            "library_revision": 1,
            "library_digest": "0" * 64,
            "description": row["description"],
            "library_attributes": {
                "appearance_homebrew": a["appearance_homebrew"],
                "source_url": a["source_url"],
            },
            "mechanics": "canonical-basic-combat-1; unsupported features listed explicitly",
        }
        Definition(row["id"], row["name"], "actor", ("creatures",), properties)


def test_pack_tactics_requires_a_living_capable_ally_next_to_the_target():
    raw = stat()
    raw["особенности"].append(
        {
            "название": "Тактика стаи",
            "описание": (
                "Существо совершает с преимуществом броски атаки по существу, если в пределах "
                "5 футов от этого существа находится как минимум один дееспособный союзник."
            ),
        }
    )
    e, program = engine_with_rules(raw)
    assert program["pack_tactics"]
    e.state["battle"] = {
        "order": ["hero", "wounded"],
        "sides": {"hero": "enemy", "wounded": "enemy"},
    }
    # The attacker itself never counts as its ally.
    assert runtime.attack_mode(e, "wounded", "hero", False) == 0
    e.state["battle"]["order"].append("helper")
    e.state["battle"]["sides"]["helper"] = "enemy"
    e.refs["helper"] = replace(e.refs["wounded"], id="helper")
    e.actors["helper"] = replace(e.actors["wounded"], id="helper")
    positions(e)["helper"]["point"] = [0, 5, 0]
    assert runtime.attack_mode(e, "wounded", "hero", False) == 1
    runtime.apply_condition(e, "helper", "stunned", "hero", 10)
    assert runtime.attack_mode(e, "wounded", "hero", False) == 0


def test_grounded_actor_does_not_climb_to_airborne_target():
    from rpg_vkr.world_library.source_geometry import approach

    e, _ = engine_with_rules()
    positions(e)["hero"]["point"] = [0, 0, 40]
    approach(e, "wounded", "hero", 5, 30)
    assert positions(e)["wounded"]["point"][2] == 0


def test_area_damage_is_rolled_once_but_each_creature_saves(monkeypatch):
    e, _ = engine_with_rules(breath_stat())
    for id in e.refs:
        positions(e)[id]["point"] = [1000, 0, 0]
    e.refs["friend"] = replace(e.refs["wounded"], id="friend")
    e.actors["friend"] = replace(e.actors["wounded"], id="friend")
    positions(e)["wounded"]["point"] = [0, 0, 0]
    positions(e)["hero"]["point"] = [10, 0, 0]
    positions(e)["friend"]["point"] = [10, 4, 0]
    e.state["source_rules_v3"]["spent"]["friend"] = {"legendary": 2}
    e.definitions["wounded_type"].properties["source_features_v3"]["magic_resistance"] = False
    calls = []

    def roll(expression, reason):
        calls.append(expression)
        return 6 if expression == "3d6" else 2

    monkeypatch.setattr(e, "roll", roll)
    runtime.turn(e, "wounded", "hero", e.definitions["wounded_type"].properties)
    assert calls.count("3d6") == 1 and calls.count("1d20") == 2
    assert e.hp("hero") == e.world.max_hp - 6 and e.hp("friend") == 6
    assert e.events[-1]["targets"] == ["hero", "friend"]


def test_condition_immunity_does_not_spend_legendary_resistance_or_rng(monkeypatch):
    e, program = engine_with_rules()
    program["condition_immunities"] = ["poisoned"]
    monkeypatch.setattr(e, "roll", lambda *args: pytest.fail("Immune effect must not roll"))
    packet, condition = runtime.save_effect(
        e,
        "hero",
        "wounded",
        {
            "ability": "constitution",
            "dc": 20,
            "magical": False,
            "half": False,
            "components": [],
            "condition": "poisoned",
            "rounds": 10,
            "repeat": "end",
        },
    )
    assert packet == [] and condition is None
    assert not e.state["source_rules_v3"]["spent"].get("wounded")


def test_high_dc_preserves_r01_exhaustion_and_natural_twenty(monkeypatch):
    e, _ = engine_with_rules()
    e.state.setdefault("owner_life", {})["hero"] = {"exhaustion": 2}
    e.char = replace(e.char, constitution=30)
    monkeypatch.setattr(e, "roll", lambda *args: 19)
    assert not runtime.saving_throw(e, "hero", "constitution", 31)
    assert e.events[-1]["total"] == 25
    monkeypatch.setattr(e, "roll", lambda *args: 20)
    assert runtime.saving_throw(e, "hero", "constitution", 40)


def test_real_registered_v3_encounter_has_deterministic_save_and_replay():
    from rpg_vkr.domain.catalog import Definition, Entity

    s = campaign(hp=12)
    raw = breath_stat()
    actions = attacks(raw)
    program = extract(raw, actions)
    definition = Definition(
        "source_fire_type",
        "Огненный испытатель",
        "actor",
        ("creatures",),
        {
            "hp_max": 80,
            "armour_class": 13,
            "strength": 14,
            "dexterity": 12,
            "constitution": 16,
            "intelligence": 10,
            "wisdom": 12,
            "charisma": 8,
            "library_rules_version": runtime.VERSION,
            "source_actions_v2": actions,
            "source_features_v3": program,
            "attack_bonus": 5,
            "damage_dice": "1d4",
        },
    )
    s.register_catalog(
        "Осмотреть сцену",
        (definition,),
        (Entity("source_fire", definition.id, parent_id="pier", state={"hp": 80}),),
        "Исходный тест нового обработчика",
        "engine-fixture",
    )
    s.perform_gameplay("encounter", {"enemies": ["source_fire"]}, "v3-encounter")
    # One complete player/NPC cycle through the public transactional API.
    if s.world.hp > 0:
        s.perform_gameplay("source_move", {"position": [0, 5, 0]}, "v3-round")
    snapshot = s.to_dict()
    restored = Session.from_dict(snapshot, version=31)
    assert dump(restored.to_dict()) == dump(snapshot)
    assert dump(restored.dice.checkpoint()) == dump(s.dice.checkpoint())
    assert "source_rules_v3" in s.gameplay


def test_out_of_range_hero_attack_never_spends_stamina_or_rng():
    from rpg_vkr.domain.catalog_actions_v2 import hit

    e, _ = engine_with_rules()
    positions(e)["wounded"]["point"] = [1000, 0, 0]
    checkpoint, stamina = e.dice.checkpoint(), e.state["st"]
    with pytest.raises(ValueError, match="range"):
        hit(e, "hero", "wounded")
    assert e.dice.checkpoint() == checkpoint and e.state["st"] == stamina


def test_source_rider_packet_with_eight_components_has_one_death_transition():
    from rpg_vkr.domain.owner_rules_runtime import life
    from rpg_vkr.world_library.damage_packets import apply

    e, _ = engine_with_rules()
    e.damage("hero", e.hp("hero") - 1)
    apply(e, "hero", [(1, "physical")] * 8, "wounded")
    assert life(e).hp == 0 and life(e).failures == 0


def test_shortbow_source_abbreviation_uses_real_range_instead_of_homebrew():
    from rpg_vkr.domain.catalog import Definition, Entity

    e, _ = engine_with_rules()
    e.definitions["test_bow_type"] = Definition(
        "test_bow_type",
        "Короткий лук",
        "item",
        ("weapons",),
        {
            "library_attributes": {
                "facts": [
                    {
                        "field": "properties",
                        "value": "Боеприпас (дис. 80/320), двуручное",
                    }
                ]
            },
        },
    )
    e.actors["test_bow"] = Entity("test_bow", "test_bow_type", "pier")
    positions(e)["wounded"]["point"] = [200, 0, 0]
    assert runtime.hero_range(e, {"source": "test_bow"}, {"category": "longbow"}, "wounded")
    assert e.events[-1]["origin"] == "source"
    assert e.events[-1]["normal"] == 80 and e.events[-1]["maximum"] == 320


def test_combat_clock_never_compresses_long_crafting_to_six_seconds():
    e, _ = engine_with_rules()
    e.action_minutes = 30
    checkpoint = dump(e.state["source_rules_v3"])
    with pytest.raises(ValueError, match="long action"):
        runtime.tick(e, "library_recipe", True)
    assert dump(e.state["source_rules_v3"]) == checkpoint


def test_unknown_condition_semantics_cannot_be_enabled_by_a_proposal():
    _, program = engine_with_rules(breath_stat())
    program["powers"][0]["effect"].update(condition="petrified", rounds=10)
    with pytest.raises(ValueError, match="complete versioned handler"):
        validate(program)


def test_v2_single_attack_count_is_preserved_when_no_new_exact_sequence(monkeypatch):
    from rpg_vkr.domain import catalog_actions_v2

    e, _ = engine_with_rules()
    properties = e.definitions["wounded_type"].properties | {"source_extra_attacks": 2}
    calls = []
    monkeypatch.setattr(catalog_actions_v2, "hit", lambda *a, **kw: calls.append(kw))
    runtime.turn(e, "wounded", "hero", properties)
    assert [r["source_attack"] for r in calls] == [0, 0, 0]
