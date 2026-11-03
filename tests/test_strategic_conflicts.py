"""Analytic expectations and conserved resources, not aesthetic model grading."""

from dataclasses import replace

import pytest

from rpg_vkr.domain.strategic_conflicts import (
    Agent,
    FoodState,
    bayes,
    cooperative_belief,
    food_options,
    pareto_front,
    plan,
    sample_transition,
)


def test_food_deficit_example_has_distinct_preferences_and_conserves_resources():
    initial = FoodState()
    options = food_options(initial)
    assert options["civilians"]["allocation"] == {"civilians": 70, "guards": 30}
    assert options["guards"]["allocation"] == {"civilians": 50, "guards": 50}
    assert options["purchase"]["allocation"] == {"civilians": 70, "guards": 50}
    assert options["purchase"]["after"]["treasury"] == 10
    assert options["purchase"]["after"]["supplier_money"] == 30
    assert (
        options["civilians"]["utilities"]["residents"] > options["guards"]["utilities"]["residents"]
    )
    assert (
        options["guards"]["utilities"]["garrison"] > options["civilians"]["utilities"]["garrison"]
    )
    for outcome in options.values():
        after = outcome["after"]
        assert sum(outcome["allocation"].values()) + after["food"] + after["supplier_food"] == 120
        assert after["treasury"] + after["supplier_money"] == 40
    assert "purchase" not in food_options(replace(initial, supplier_available=False))
    assert "purchase" not in food_options(replace(initial, treasury=29))


def test_pareto_equality_is_not_domination_and_agent_scales_are_fixed():
    assert pareto_front({"a": (1, 0), "b": (0, 1), "same": (1, 0), "bad": (0, 0)}) == (
        "a",
        "b",
        "same",
    )
    assert Agent("merchant", (1, 1)).utility((20, -10), (100, 100)) == pytest.approx(0.05)
    with pytest.raises(ValueError):
        Agent("broken", (float("nan"),))
    with pytest.raises(ValueError):
        FoodState(food=-1)


def test_bayesian_evidence_and_repeated_cooperation_are_explicit():
    posterior = bayes({"honest": 0.5, "deceptive": 0.5}, {"honest": 0.9, "deceptive": 0.1})
    assert posterior == {"honest": 0.9, "deceptive": 0.1}
    assert cooperative_belief(8, 1) > cooperative_belief(1, 8)
    with pytest.raises(ValueError):
        bayes({"a": 1}, {"a": 0})


def test_stochastic_transition_reproducibility_frequency_and_bounded_planning():
    outcomes = [(0.25, "rain"), (0.75, "clear")]
    assert sample_transition(outcomes, seed=7) == sample_transition(outcomes, seed=7)
    observed = sum(sample_transition(outcomes, seed=n) == "rain" for n in range(2000)) / 2000
    assert 0.21 < observed < 0.29
    scores = plan(
        0,
        lambda s: ("save", "spend") if s < 2 else (),
        lambda s, a: [(1, s + 1)],
        lambda s, a, n: 2 if a == "save" else 1,
    )
    assert scores["save"] == pytest.approx(3.8)
    with pytest.raises(ValueError, match="budget"):
        plan(0, lambda s: ("a", "b"), lambda s, a: [(1, s + 1)], lambda s, a, n: 0, budget=1)


def test_food_negotiation_transfers_actual_rations_and_replays():
    from test_free_actions_pipeline import campaign

    from rpg_vkr.application import Session

    success = False
    for seed in range(10):
        s = campaign(seed=seed, guard=True)
        s.perform_gameplay("wait", {"minutes": 1440}, "day")
        w = s.gameplay["living_world"]
        total = sum(v["food"] for v in w["stocks"].values()) + sum(
            p["food"] for p in w["residents"].values()
        )
        s.submit("Предлагаю распределить продовольствие между жителями и гарнизоном")
        w = s.gameplay["living_world"]
        assert total == sum(v["food"] for v in w["stocks"].values()) + sum(
            p["food"] for p in w["residents"].values()
        )
        record = next(iter(s.gameplay["food_negotiations"].values()))
        assert record["reactions"] and all(n >= 0 for n in record["transfers"].values())
        assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
        if record["accepted"]:
            assert sum(record["transfers"].values()) > 0
            success = True
            break
    assert success
