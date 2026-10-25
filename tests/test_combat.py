"""Independent examples for original combat rules, separate from SRD claims."""

from dataclasses import replace

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.combat import ActorState, CombatState, perform_combat
from rpg_vkr.domain.dice import D20Roll
from rpg_vkr.domain.progression import ARCHETYPES, HeroProgress
from rpg_vkr.domain.world import WorldState


class ScriptedDice:
    def __init__(self, values):
        self.values = iter(values)
        self.count = 0

    def roll_d20(self):
        self.count += 1
        return D20Roll(self.count, next(self.values))


def hero():
    return Session.create_hero(
        Character(
            name="Мира", **dict(zip(ABILITY_NAMES, ARCHETYPES["fighter"].scores, strict=True))
        ),
        "fighter",
        seed=5,
    )


def test_hit_and_damage_are_separate_and_low_bonus_keeps_strength_and_weapon():
    dice = ScriptedDice([12, 1, 3])
    result = perform_combat(
        CombatState(),
        WorldState(location="road"),
        Character(strength=16),
        "fighter",
        "атаковать волка",
        dice,
    )
    assert result.check.succeeded
    assert result.state.actor("wolf").hp == 4  # 10 - (weapon3 + Strength3 + bonus0)
    assert result.world.hp == 12  # counter3+1 misses defence11
    assert len(result.rolls) == 3
    assert "база 6 + бонус 0" in result.text


def test_miss_never_rolls_damage_and_still_angers_a_neutral_target():
    result = perform_combat(
        CombatState(),
        WorldState(),
        Character(strength=8),
        "fighter",
        "атаковать стражника",
        ScriptedDice([1, 1]),
    )
    assert not result.check.succeeded
    assert result.state.actor("guard").hp == 18
    assert result.state.actor("guard").disposition == "hostile"
    assert len(result.rolls) == 2


@pytest.mark.parametrize(
    "die,grade", [(20, "очень удачно"), (10, "удачно"), (5, "малоудачно"), (1, "неудачно")]
)
def test_four_approach_outcomes(die, grade):
    # Dex10 has no modifier; conditional counter1 always misses.
    values = [die] if die >= 15 else [die, 1]
    result = perform_combat(
        CombatState(),
        WorldState(location="road"),
        Character(dexterity=10),
        "fighter",
        "подкрасться к волку",
        ScriptedDice(values),
    )
    assert grade in result.text
    assert result.state.active == "wolf"
    assert result.state.surprise == (die >= 15)


def test_hidden_attack_multiplies_once_and_victory_has_no_counterattack():
    first = perform_combat(
        CombatState(),
        WorldState(location="road"),
        Character(strength=16),
        "fighter",
        "подкрасться к волку",
        ScriptedDice([20]),
    )
    result = perform_combat(
        first.state,
        first.world,
        Character(strength=16),
        "fighter",
        "атаковать волка",
        ScriptedDice([12, 1]),
    )
    assert result.victory
    assert result.state.actor("wolf").hp == 0
    assert result.state.active is None
    assert not result.state.surprise
    assert result.world.hp == 12
    assert len(result.rolls) == 2
    assert "×2 = 12" in result.text


def test_surprise_is_lost_on_miss_and_cannot_be_rerolled_in_open_combat():
    state = CombatState(active="wolf", surprise=True)
    result = perform_combat(
        state,
        WorldState(location="road"),
        Character(strength=8),
        "fighter",
        "атаковать",
        ScriptedDice([1, 1]),
    )
    assert not result.state.surprise
    blocked = perform_combat(
        result.state, result.world, Character(), "fighter", "подкрасться к волку", ScriptedDice([])
    )
    assert blocked.state == result.state
    assert not blocked.rolls


def test_unseen_neutral_animal_is_not_hostile_until_attack():
    result = perform_combat(
        CombatState(),
        WorldState(location="road"),
        Character(dexterity=16),
        "scout",
        "подкрасться к кабану",
        ScriptedDice([20]),
    )
    assert result.state.actor("boar").disposition == "neutral"
    attacked = perform_combat(
        result.state,
        result.world,
        Character(strength=8),
        "scout",
        "атаковать кабана",
        ScriptedDice([1, 1]),
    )
    assert attacked.state.actor("boar").disposition == "hostile"


def test_bandage_costs_an_action_and_enemy_can_respond():
    result = perform_combat(
        CombatState(active="wolf"),
        WorldState(location="road", hp=5),
        Character(),
        "fighter",
        "использовать бинт",
        ScriptedDice([20, 20]),
    )
    assert result.world.bandages == 0
    assert result.world.hp == 7  # +4 healing, then -2 damage
    assert len(result.rolls) == 2
    no_bandage = perform_combat(
        result.state, result.world, Character(), "fighter", "использовать бинт", ScriptedDice([])
    )
    assert not no_bandage.rolls
    assert no_bandage.world == result.world


def test_successful_retreat_breaks_engagement_but_keeps_hostility_and_wounds():
    state = CombatState(active="wolf").update(ActorState("wolf", 4, "hostile"))
    result = perform_combat(
        state,
        WorldState(location="road"),
        Character(dexterity=12),
        "fighter",
        "отступить",
        ScriptedDice([20]),
    )
    assert result.state.active is None
    assert result.state.actor("wolf") == state.actor("wolf")
    assert len(result.rolls) == 1


def test_zero_health_ends_combat_without_negative_hp():
    result = perform_combat(
        CombatState(active="wolf"),
        WorldState(location="road", hp=1),
        Character(strength=8),
        "fighter",
        "атаковать",
        ScriptedDice([1, 20, 20]),
    )
    assert result.world.hp == 0
    assert result.state.active is None
    blocked = perform_combat(
        result.state, result.world, Character(), "fighter", "атаковать волка", ScriptedDice([])
    )
    assert blocked.world.hp == 0
    assert not blocked.rolls


@pytest.mark.parametrize(
    "changes", [{"hp": -1}, {"hp": True}, {"disposition": "friendly"}, {"id": "fake"}]
)
def test_actor_validation_rejects_bad_state(changes):
    with pytest.raises(ValueError):
        replace(ActorState("wolf", 10, "hostile"), **changes)


def test_real_session_victory_progression_and_shared_rng_replay():
    session = hero()
    session.submit("изучить учебник")
    session.submit("идти на дорогу")
    session.submit("подкрасться к волку")  # seed5: 20
    victory = session.submit("атаковать волка")  # 9 hits, 12 for power
    assert victory.combat.outcome.victory
    assert session.progress.xp == 4
    assert session.progress.level == 2
    assert session.character.strength == 17
    assert session.world.max_hp == 14
    restored = Session.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()
    before = restored.progress
    restored.submit("атаковать волка")
    assert restored.progress == before
    assert restored.submit("бросить d20").roll.value == 17  # fourth actual roll


def test_hostility_stops_trade_and_persists_without_destroying_old_dialogue():
    session = Session(seed=42)
    for command in ("узнать дорогу на рынок", "идти на рынок", "подойти к торговцу"):
        session.submit(command)
    session.submit("поссориться с торговцем")
    assert session.combat.actor("merchant").disposition == "hostile"
    assert not session.world.trading
    before = session.world
    assert "враждебен" in session.submit("купить бинт").text
    assert session.world == before
    restored = Session.from_dict(session.to_dict())
    assert restored.combat == session.combat
    assert restored.turns[2].actor_id == "merchant"


def test_pending_combat_blocks_teleport_study_and_free_checks_without_rng_use():
    session = hero()
    session.submit("идти на дорогу")
    session.submit("подкрасться к волку")
    before = session.dice.checkpoint()
    for command in ("идти на рынок", "изучить учебник", "проверить силу", "бросить d20"):
        assert "схватка" in session.submit(command).text
    assert session.world.location == "road"
    assert session.dice.checkpoint() == before
    assert session.progress.xp == 0


def test_reward_failure_rolls_back_entire_combat_and_rng(monkeypatch):
    session = hero()
    session.submit("идти на дорогу")
    session.submit("подкрасться к волку")
    previous = session.to_dict()
    checkpoint = session.dice.checkpoint()

    def fail(*args, **kwargs):
        raise ValueError("simulated reward failure")

    monkeypatch.setattr(HeroProgress, "award", fail)
    with pytest.raises(ValueError):
        session.submit("атаковать волка")
    assert session.to_dict() == previous
    assert session.dice.checkpoint() == checkpoint


@pytest.mark.parametrize("command", ["уклониться", "отступить", "использовать бинт"])
def test_unseen_neutral_target_can_be_left_or_revealed_without_invalid_state(command):
    state = CombatState(active="boar", surprise=True)
    result = perform_combat(
        state,
        WorldState(location="road", hp=8),
        Character(),
        "fighter",
        command,
        ScriptedDice([20, 1]),
    )
    assert not result.state.surprise
    if command == "отступить":
        assert result.state.active is None
        assert result.state.actor("boar").disposition == "neutral"
    else:
        assert result.state.actor("boar").disposition == "hostile"
