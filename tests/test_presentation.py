"""Recorded outcomes get readable views without changing rules, state or RNG."""

from dataclasses import replace

import pytest

from rpg_vkr.application import Session, Turn
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.combat import CombatState, perform_combat
from rpg_vkr.domain.combat_record import CombatRecord
from rpg_vkr.domain.dice import D20Roll
from rpg_vkr.domain.world import WorldState
from rpg_vkr.narrative.presentation import present_turn


class FixedDice:
    def __init__(self, values):
        self.values = iter(values)
        self.count = 0

    def roll_d20(self):
        self.count += 1
        return D20Roll(self.count, next(self.values))


def combat_turn(command, values, *, world=None, state=None, character=None):
    world = world or WorldState(location="road")
    state = state or CombatState()
    character = character or Character(strength=16, dexterity=10)
    outcome = perform_combat(state, world, character, "fighter", command, FixedDice(values))
    record = CombatRecord(state, world, character, "fighter", command, outcome)
    return Turn(
        command,
        "Серый волк",
        outcome.text,
        outcome.rolls[0] if outcome.rolls else None,
        outcome.check,
        outcome.actor_id,
        record,
    )


def test_low_power_bonus_keeps_base_and_all_math_outside_story():
    turn = combat_turn("атаковать волка", [12, 1, 3])
    view = present_turn(turn)
    assert view.title == "Попадание · урон 6"
    assert "вклад силы и оружия сохранён" in view.story
    assert "12 + 3 = 15" in view.details
    assert "Оружие: 3; вклад Силы: 3" in view.details
    assert "(6 + 0) × 1 = 6" in view.details
    assert "№3 — ответ противника" in view.details
    assert "3 + 1 = 4" in view.details
    assert "d20" not in view.story + view.details
    assert "=" not in view.story
    assert "слабая атака" not in view.story.casefold()


def test_hidden_attack_explains_multiplier_once_and_victory_has_no_counter():
    state = replace(CombatState(), active="wolf", surprise=True)
    turn = combat_turn("атаковать волка", [12, 1], state=state)
    view = present_turn(turn)
    assert view.title == "Скрытая атака ×2 · урон 12"
    assert "благодаря незамеченному подходу" in view.story
    assert "(6 + 0) × 2 = 12" in view.details
    assert "противник повержен" in view.story
    assert "ответ противника" not in view.details
    assert turn.combat.outcome.state.actor("wolf").hp == 0


def test_miss_has_no_damage_throw_and_explains_lost_surprise():
    state = replace(CombatState(), active="wolf", surprise=True)
    turn = combat_turn("атаковать волка", [1, 1], state=state)
    view = present_turn(turn)
    assert view.title == "Промах · урона нет"
    assert "Неожиданность потеряна" in view.story
    assert "Броска на силу удара не было" in view.story
    assert "усиление удара" not in view.details
    assert "№2 — ответ противника" in view.details


@pytest.mark.parametrize(
    "value,expected",
    [
        (20, "Незамеченный подход"),
        (10, "заметили в конце"),
        (5, "на полпути"),
        (1, "заметили сразу"),
    ],
)
def test_four_approach_grades_and_threshold_explanation(value, expected):
    turn = combat_turn("подкрасться к волку", [value] if value >= 15 else [value, 1])
    view = present_turn(turn)
    assert expected in view.title
    assert "Порог 15 относится к полностью незамеченному подходу" in view.details
    assert "=" not in view.story


@pytest.mark.parametrize(
    "command,roll,title",
    [
        ("уклониться", 10, "Успешное уклонение"),
        ("уклониться", 1, "Уклонение не удалось"),
        ("отступить", 10, "Успешное отступление"),
        ("отступить", 1, "Отступить не удалось"),
    ],
)
def test_manoueuvres_explain_actual_outcome(command, roll, title):
    turn = combat_turn(
        command, [roll] if roll >= 10 else [roll, 1], state=replace(CombatState(), active="wolf")
    )
    view = present_turn(turn)
    assert view.title == title
    assert "Нужно не меньше 10" in view.details
    assert ("ответ противника" in view.details) == (roll < 10)


def test_bandage_explains_healing_and_counter_damage_separately_at_zero_health():
    turn = combat_turn(
        "использовать бинт",
        [20, 20],
        world=replace(WorldState(location="road"), hp=1),
        state=replace(CombatState(), active="wolf"),
    )
    view = present_turn(turn)
    assert view.title == "Лечение · +4 здоровья"
    assert "потеряли 2 здоровья" in view.story
    assert "Восстановлено: 4" in view.details
    assert "Потеряно здоровья: 2" in view.details
    assert turn.combat.outcome.world.hp == 3


def test_counter_damage_is_capped_at_remaining_health():
    turn = combat_turn(
        "атаковать волка", [1, 20, 20], world=replace(WorldState(location="road"), hp=1)
    )
    view = present_turn(turn)
    assert "Вы потеряли 1 здоровья" in view.story
    assert "Вы выбыли" in view.story
    assert "база 1 + прибавка 1 = 2" in view.details
    assert "Потеряно здоровья: 1" in view.details


def test_repeated_presentation_is_read_only_and_does_not_reroll():
    session = Session(seed=5, world=WorldState(location="road"))
    turn = session.submit("атаковать волка")
    before = session.to_dict()
    checkpoint = session.dice.checkpoint()
    first = present_turn(turn)
    for _ in range(10):
        assert present_turn(turn) == first
    assert session.to_dict() == before
    assert session.dice.checkpoint() == checkpoint
    assert present_turn(Session.from_dict(before).turns[-1]) == first


def test_negative_modifier_is_readable_and_standalone_roll_has_no_success_claim():
    session = Session(seed=42)
    view = present_turn(session.submit("проверить харизму"))
    assert "4 − 1 = 3" in view.details
    assert "Харизма — неудача" in view.story
    assert "мир не изменился" in view.story
    roll = present_turn(session.submit("бросить кубик"))
    assert roll.title == "Кубик — 1"
    assert "Проверки успеха и урона не было" in roll.details


def test_exploration_preserves_consequences_and_no_extra_dice_are_used():
    session = Session(seed=42, world=WorldState(location="road"))
    turn = session.submit("исследовать дорогу")
    before = session.to_dict()
    view = present_turn(turn)
    assert "Потеряно здоровья: 3" in view.story
    assert "=" not in view.story
    assert "4 + 1 = 5" in view.details
    assert session.to_dict() == before


def test_unknown_historical_action_does_not_gain_new_effect_or_narration():
    turn = Turn("атаковать волка", "Рассказчик", "Я пока не понимаю это действие.")
    view = present_turn(turn)
    assert view.story == turn.text
    assert view.details == "Бросок не требуется."
