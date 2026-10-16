"""Validate homebrew transitions, conservation and one-time rewards."""

from dataclasses import asdict, replace

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.domain.world import WorldState, perform_action


def test_complete_delivery_trade_and_healing_cycle():
    session = Session(seed=42)
    for command in ["взять поручение", "идти на дорогу", "исследовать дорогу"]:
        session.submit(command)
    assert session.world.hp == 9
    assert session.world.explored
    assert session.world.basket == 1
    for command in ["идти на рынок", "доставить корзину", "купить бинт", "использовать бинт"]:
        session.submit(command)
    assert session.world.hp == 12
    assert session.world.gold == 12
    assert session.world.bandages == 1
    assert session.world.basket == 0
    assert session.world.quest == "completed"
    assert session.world.shop_stock == 2
    before = session.world
    session.submit("доставить корзину")
    session.submit("взять поручение")
    assert session.world == before


def test_trade_conserves_money_and_items_and_cannot_generate_profit():
    session = Session(seed=42, world=WorldState(location="market"))
    starting = session.world
    for command in ["купить бинт", "продать бинт"]:
        session.submit(command)
        state = session.world
        assert state.gold + state.shop_gold == starting.gold + starting.shop_gold
        assert state.bandages + state.shop_stock == starting.bandages + starting.shop_stock
    assert session.world.gold == starting.gold - 2


@pytest.mark.parametrize(
    ("state", "command"),
    [
        (WorldState(), "купить бинт"),
        (WorldState(location="market", gold=2), "купить бинт"),
        (WorldState(location="market", shop_stock=0), "купить бинт"),
        (WorldState(location="market", bandages=0), "продать бинт"),
        (WorldState(location="market", shop_gold=0), "продать бинт"),
        (WorldState(), "использовать бинт"),
        (WorldState(hp=5, bandages=0), "использовать бинт"),
        (WorldState(), "доставить корзину"),
        (WorldState(quest="active", basket=1), "доставить корзину"),
        (WorldState(location="market"), "взять поручение"),
        (WorldState(), "исследовать дорогу"),
    ],
)
def test_blocked_actions_keep_resources_and_do_not_consume_dice(state, command):
    dice = DiceRoller(seed=42)
    outcome = perform_action(state, command, Character(), dice)
    assert outcome.state == state
    assert outcome.roll is None
    assert dice.roll_d20().value == 4


def test_road_reward_and_risk_are_one_time_only():
    for seed, expected_hp, expected_gold in [(42, 9, 10), (5, 12, 12)]:
        session = Session(seed=seed, world=WorldState(location="road"))
        turn = session.submit("исследовать дорогу")
        assert turn.check is not None
        assert session.world.hp == expected_hp
        assert session.world.gold == expected_gold
        previous = session.world
        assert session.submit("исследовать дорогу").roll is None
        assert session.world == previous
        assert session.submit("бросить d20").roll.index == 2


def test_bandage_caps_healing_and_is_consumed_once():
    session = Session(world=WorldState(hp=11))
    session.submit("использовать бинт")
    assert session.world.hp == 12
    assert session.world.bandages == 0
    session.submit("использовать бинт")
    assert session.world.hp == 12
    assert session.world.bandages == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"hp": -1},
        {"hp": 13},
        {"gold": -1},
        {"bandages": True},
        {"quest": "active", "basket": 0},
        {"basket": 1},
        {"explored": 1},
        {"location": "elsewhere"},
        {"location": []},
        {"extra": 1},
    ],
)
def test_invalid_world_data_is_rejected(changes):
    with pytest.raises(ValueError):
        WorldState.from_dict(asdict(WorldState()) | changes)


def test_profile_edit_preserves_resources_and_old_check_results():
    session = Session(seed=42, world=WorldState(hp=7, gold=4))
    session.submit("проверить силу")
    world = session.world
    assert session.edit_character(Character(name="Мира", strength=18))
    assert session.world == world
    assert session.turns[0].check.modifier == 2
    assert session.submit("проверить силу").check.modifier == 4
    assert not session.edit_character(session.character)
    restored = Session.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()


def test_session_worlds_are_independent():
    first = Session(seed=42)
    second = Session(seed=42)
    first.submit("взять поручение")
    assert second.world == WorldState()
    assert first.world != second.world


def test_resource_validation_prevents_partial_commit_at_limit():
    state = replace(WorldState(), location="market", quest="active", basket=1, gold=1_000_000)
    session = Session(seed=42, world=state)
    with pytest.raises(ValueError):
        session.submit("доставить корзину")
    assert session.world == state
    assert not session.turns


def test_failed_random_transition_restores_rng_and_keeps_saves_replayable():
    state = WorldState(location="road", gold=1_000_000)
    session = Session(seed=5, world=state)
    with pytest.raises(ValueError):
        session.submit("исследовать дорогу")
    assert session.world == state
    assert not session.turns
    assert session.submit("бросить d20").roll.value == 20
    assert session.turns[-1].roll.index == 1
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_legacy_observe_and_dialogue_follow_current_location():
    session = Session(seed=42)
    assert "следы телеги" in session.submit("осмотреться").text
    session.submit("идти на рынок")
    assert "на рынке" in session.submit("осмотреться").text
    assert "Торговец" in session.submit("поговорить").text
    assert "осталась у ворот" in session.submit("помочь").text
    assert session.world.gold == 10
    assert session.submit("бросить d20").roll.value == 4
