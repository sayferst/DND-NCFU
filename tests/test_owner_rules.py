"""Independent SRD boundary examples and direct owner-approved homebrew expectations."""

from dataclasses import replace

import pytest

from rpg_vkr.domain.owner_rules import (
    Life,
    add_exhaustion,
    agreement_eligibility,
    check,
    damage,
    death_save,
    heal,
    long_rest,
    overcast,
    speed,
    stabilize,
)


def test_stabilization_is_not_healing_and_healing_does_not_resurrect():
    wounded = Life(0, 12, successes=1, failures=2)
    stable = stabilize(wounded)
    assert stable.hp == 0 and stable.unconscious and stable.stable
    assert stable.successes == stable.failures == 0
    awake = heal(stable, 1)
    assert awake.hp == 1 and not awake.unconscious and not awake.stable
    dead = damage(Life(0, 12), 12)
    assert dead.dead and heal(dead, 100) == dead


@pytest.mark.parametrize(
    "roll,successes,failures,hp",
    [(1, 0, 2, 0), (9, 0, 1, 0), (10, 1, 0, 0), (19, 1, 0, 0), (20, 0, 0, 1)],
)
def test_death_save_examples(roll, successes, failures, hp):
    result = death_save(Life(0, 12), roll)
    assert (result.successes, result.failures, result.hp) == (successes, failures, hp)


def test_three_saves_stabilize_three_failures_kill_and_exhaustion_applies():
    stable = death_save(Life(0, 12, successes=2, failures=1), 10)
    assert stable.stable and stable.successes == stable.failures == 0
    assert death_save(Life(0, 12, failures=2), 9).dead
    assert death_save(Life(0, 12, exhaustion=1), 10).failures == 1
    assert death_save(Life(0, 12, exhaustion=5), 20).hp == 1


def test_damage_at_zero_critical_massive_and_nonlethal_are_distinct():
    stable = Life(0, 12, stable=True)
    assert damage(stable, 0) == stable
    assert damage(stable, 1).failures == 1 and not damage(stable, 1).stable
    assert damage(stable, 1, critical=True).failures == 2
    assert damage(stable, 12).dead
    assert not damage(Life(6, 12), 17).dead
    assert damage(Life(6, 12), 18).dead
    knockout = damage(Life(3, 12), 30, nonlethal=True)
    assert knockout.hp == 0 and knockout.stable and knockout.unconscious and not knockout.dead


def test_exhaustion_penalty_speed_rest_and_sixth_level_death():
    tired = Life(5, 12, exhaustion=3)
    assert speed(tired, 30) == 15
    rested = long_rest(tired)
    assert rested.hp == 12 and rested.exhaustion == 2
    assert long_rest(rested).exhaustion == 1
    assert add_exhaustion(Life(12, 12, exhaustion=5), 1).dead
    with pytest.raises(ValueError):
        long_rest(Life(0, 12, stable=True))


def test_overcast_pays_full_price_can_reach_zero_and_does_not_treat_payment_as_damage():
    paid, record = overcast(Life(4, 12), 0, 2, "hp")
    assert paid.hp == 0 and paid.unconscious and paid.failures == 0
    assert record["hp_spent"] == 4 and record["dc"] == 14
    with pytest.raises(ValueError, match="Insufficient HP"):
        overcast(Life(2, 12), 0, 2, "hp")
    paid, record = overcast(Life(12, 12, exhaustion=4), 1, 4, "exhaustion")
    assert paid.dead and record["exhaustion_added"] == 2
    for missing in [0, 4]:
        with pytest.raises(ValueError):
            overcast(Life(12, 12), 0, missing, "hp")
    with pytest.raises(ValueError, match="explicitly"):
        overcast(Life(12, 12), 0, 1, None)


def test_high_d20_has_no_effect_when_goal_is_unreachable():
    for face in range(1, 21):
        result = check(face, 40, 10, goal_possible=False)
        assert result["natural"] is None and not result["succeeded"]
    best = check(20, -20, 30)
    assert best["outcome"] == "best_possible" and best["total"] == 0
    one = check(1, 20, 10)
    assert one["succeeded"] and one["complication"] and one["total"] == 21


def test_agreements_require_known_authority_feasibility_and_vital_limits():
    assert (
        agreement_eligibility(authority=True, feasible=True, constraints=[True, True]) == "eligible"
    )
    for kwargs in [
        dict(authority=None, feasible=True, constraints=[]),
        dict(authority=True, feasible=True, constraints=[None]),
    ]:
        assert agreement_eligibility(**kwargs) == "clarification_required"
    for key in ["authority", "feasible"]:
        values = dict(authority=True, feasible=True, constraints=[True])
        values[key] = False
        assert agreement_eligibility(**values) == "outside_authority_or_vital_limits"
    assert (
        agreement_eligibility(authority=True, feasible=True, constraints=[False])
        == "outside_authority_or_vital_limits"
    )


@pytest.mark.parametrize(
    "bad",
    [
        dict(hp=-1),
        dict(hp=13),
        dict(exhaustion=6),
        dict(dead=True),
        dict(stable=True),
        dict(failures=3),
    ],
)
def test_impossible_life_states_rejected(bad):
    with pytest.raises(ValueError):
        replace(Life(6, 12), **bad)
