"""New rules replay independently; legacy sessions retain their original rules."""

from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.d20_progression import (
    D20Progress,
    level_for_xp,
    rank_limit,
    required_xp,
    resolve_skill_check,
)


@pytest.mark.parametrize("level", range(1, 21))
def test_level_thresholds_and_rewards(level):
    xp = required_xp(level)
    p = D20Progress() if not xp else D20Progress().grant_xp("milestone", xp, "Значимый результат")
    assert p.level == level
    assert p.skill_points == 13 + 2 * (level - 1)
    assert p.attribute_rewards == level // 4
    assert p.talent_rewards == 1 + level // 5
    if level > 1:
        assert level_for_xp(xp - 1) == level - 1
    assert D20Progress.from_dict(p.to_dict()) == p


def test_skill_costs_unlocks_and_selected_two_points_per_rank():
    p = D20Progress()
    p = p.train("smithing", "learn1").train("smithing", "learn2")
    assert p.rank("smithing") == 2 and p.bonus("smithing") == 4
    assert p.skill_points == 10
    with pytest.raises(ValueError, match="Ранг недоступен"):
        p.train("smithing", "too_early")
    spent = 3
    for level, rank in ((5, 3), (10, 4), (15, 5)):
        p = p.grant_xp(f"reach:{level}", required_xp(level) - p.xp, "Новая веха")
        p = p.train("smithing", f"rank:{rank}")
        spent += rank
        assert p.skill_points == 13 + 2 * (level - 1) - spent
        assert p.bonus("smithing") == 2 * rank
    assert spent == 15
    with pytest.raises(ValueError):
        p.train("smithing", "rank6")


def test_duplicate_achievement_does_not_grant_points_twice():
    p = D20Progress().grant_xp("quest:one", 100, "Задача решена")
    before = p.to_dict()
    with pytest.raises(ValueError, match="Повторное"):
        p.grant_xp("quest:one", 100, "Повтор запроса")
    assert p.to_dict() == before


def test_sequential_level_one_to_twenty_survives_each_reload():
    p = D20Progress().train("athletics", "start")
    for level in range(2, 21):
        p = p.grant_xp(f"milestone:{level}", required_xp(level) - p.xp, "Новая веха")
        p = D20Progress.from_dict(p.to_dict())
        assert p.level == level and p.skill_points == 13 + 2 * (level - 1) - 1
    assert p.xp == 19000 and p.attribute_rewards == 5 and p.talent_rewards == 5


def test_spending_cannot_use_future_rewards_or_overdraw_budget():
    p = D20Progress()
    for i, skill in enumerate(("athletics", "acrobatics", "stealth", "perception")):
        p = p.train(skill, f"first:{i}").train(skill, f"second:{i}")
    assert p.skill_points == 1
    p = p.train("survival", "last")
    with pytest.raises(ValueError, match="Недостаточно"):
        p.train("knowledge", "overdraw")
    data = D20Progress().grant_xp("level5", 1000, "Веха").train("smithing", "s1")
    data = data.train("smithing", "s2").train("smithing", "s3").to_dict()
    data["events"] = data["events"][1:] + data["events"][:1]
    with pytest.raises(ValueError):
        D20Progress.from_dict(data)


@pytest.mark.parametrize(
    "field,value", [("amount", True), ("amount", 1.5), ("kind", []), ("subject", "unknown")]
)
def test_invalid_saved_events_rejected(field, value):
    data = D20Progress().train("smithing", "learn").to_dict()
    data["events"][0][field] = value
    with pytest.raises(ValueError):
        D20Progress.from_dict(data)


def test_check_has_explicit_math_and_no_automatic_natural_twenty_success():
    p = D20Progress().train("smithing", "learn1").train("smithing", "learn2")
    result = resolve_skill_check(p, "smithing", 16, 12, 20, equipment=2, situational=-1)
    assert (result.ability_bonus, result.skill_bonus, result.total, result.succeeded) == (
        3,
        4,
        20,
        True,
    )
    assert not resolve_skill_check(D20Progress(), "arcana", 8, 20, 30).succeeded
    assert rank_limit(20) == 5


def test_new_rules_do_not_mutate_legacy_session():
    old = Session(seed=42)
    before = deepcopy(old.to_dict()), old.dice.checkpoint()
    p = D20Progress().grant_xp("achievement", 19000, "Важный результат")
    p = p.train("repair", "repair1")
    resolve_skill_check(p, "repair", 14, 10, 15)
    assert (old.to_dict(), old.dice.checkpoint()) == before
    assert Session.from_dict(old.to_dict()).to_dict() == before[0]
