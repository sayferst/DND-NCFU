"""Small finite stochastic games, independent of narrator and external services.

Utilities and food scenarios are explicit research assumptions, not SRD rules
or measured human preferences. Different actors keep different utility vectors.
"""

from dataclasses import asdict, dataclass, replace
from math import isfinite
from random import Random


def finite(value):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError("Expected a finite number")
    return value


def probabilities(values):
    if not values or any(finite(v) < 0 for v in values) or abs(sum(values) - 1) > 1e-9:
        raise ValueError("Probabilities must be nonnegative and sum to one")


@dataclass(frozen=True)
class Agent:
    id: str
    weights: tuple[float, ...]
    risk_aversion: float = 0

    def __post_init__(self):
        if not self.id or not self.weights or any(finite(w) < 0 for w in self.weights):
            raise ValueError("Invalid agent preferences")
        if sum(self.weights) <= 0 or finite(self.risk_aversion) < 0:
            raise ValueError("Invalid agent weights or risk")

    def utility(self, changes, scales, *, risk=0, cost=0):
        if len(changes) != len(scales) or len(changes) != len(self.weights):
            raise ValueError("Utility dimensions differ")
        if any(finite(s) <= 0 for s in scales) or finite(risk) < 0 or finite(cost) < 0:
            raise ValueError("Invalid scale, risk or cost")
        return (
            sum(
                w * finite(x) / scale
                for w, x, scale in zip(self.weights, changes, scales, strict=True)
            )
            / sum(self.weights)
            - self.risk_aversion * risk
            - cost
        )


def pareto_front(vectors):
    if not vectors:
        return ()
    size = len(next(iter(vectors.values())))
    if not size or any(len(v) != size for v in vectors.values()):
        raise ValueError("Unequal payoff dimensions")
    for v in vectors.values():
        for x in v:
            finite(x)
    return tuple(
        name
        for name, v in vectors.items()
        if not any(
            all(a >= b for a, b in zip(other, v, strict=True))
            and any(a > b for a, b in zip(other, v, strict=True))
            for other in vectors.values()
        )
    )


def bayes(prior, likelihood):
    if set(prior) != set(likelihood):
        raise ValueError("Evidence hypotheses differ")
    probabilities(list(prior.values()))
    if any(not 0 <= finite(v) <= 1 for v in likelihood.values()):
        raise ValueError("Invalid likelihood")
    evidence = sum(prior[k] * likelihood[k] for k in prior)
    if evidence <= 0:
        raise ValueError("Observation has zero probability")
    return {k: prior[k] * likelihood[k] / evidence for k in prior}


def cooperative_belief(cooperations, betrayals):
    if any(type(v) is not int or v < 0 for v in (cooperations, betrayals)):
        raise ValueError("Invalid interaction counts")
    return (cooperations + 1) / (cooperations + betrayals + 2)


def sample_transition(transitions, *, seed):
    probabilities([p for p, _ in transitions])
    rng = Random(seed)
    point, cumulative = rng.random(), 0
    for p, state in transitions:
        cumulative += p
        if point < cumulative:
            return state
    return transitions[-1][1]


def plan(state, actions, transition, reward, *, horizon=2, discount=0.9, budget=1000):
    """Bounded expected-value planning; caller supplies only the actor's observations."""
    if type(horizon) is not int or not 1 <= horizon <= 4 or not 0 <= finite(discount) <= 1:
        raise ValueError("Invalid planning bounds")
    if type(budget) is not int or not 1 <= budget <= 100000:
        raise ValueError("Invalid planning budget")
    remaining = budget

    def search(current, depth):
        nonlocal remaining
        if not depth:
            return {}
        scores = {}
        for action in actions(current):
            remaining -= 1
            if remaining < 0:
                raise ValueError("Planning budget exceeded")
            outcomes = transition(current, action)
            probabilities([p for p, _ in outcomes])
            scores[action] = sum(
                p
                * (
                    finite(reward(current, action, after))
                    + discount * max(search(after, depth - 1).values(), default=0)
                )
                for p, after in outcomes
                if p
            )
        return scores

    return search(state, horizon)


@dataclass(frozen=True)
class FoodState:
    food: int = 100
    civilian_need: int = 70
    guard_need: int = 50
    treasury: int = 40
    supplier_food: int = 20
    supplier_money: int = 0
    purchase_price: int = 30
    supplier_available: bool = True

    def __post_init__(self):
        values = asdict(self)
        values.pop("supplier_available")
        if any(type(v) is not int or v < 0 for v in values.values()):
            raise ValueError("Food and money are finite nonnegative integers")
        if type(self.supplier_available) is not bool:
            raise ValueError("Supplier availability must be explicit")


def food_options(state):
    result = {}
    available = state.food
    for policy in ("civilians", "guards", "balanced", "purchase"):
        buying = policy == "purchase"
        deficit = max(0, state.civilian_need + state.guard_need - available)
        if buying and (
            not state.supplier_available
            or deficit == 0
            or state.supplier_food < deficit
            or state.treasury < state.purchase_price
        ):
            continue
        stock = available + (deficit if buying else 0)
        if policy == "guards":
            guards = min(state.guard_need, stock)
            civilians = min(state.civilian_need, stock - guards)
        elif policy == "balanced":
            need = state.civilian_need + state.guard_need
            civilians = min(state.civilian_need, stock * state.civilian_need // max(1, need))
            guards = min(state.guard_need, stock - civilians)
        else:
            civilians = min(state.civilian_need, stock)
            guards = min(state.guard_need, stock - civilians)
        after = replace(
            state,
            food=stock - civilians - guards,
            treasury=state.treasury - (state.purchase_price if buying else 0),
            supplier_food=state.supplier_food - (deficit if buying else 0),
            supplier_money=state.supplier_money + (state.purchase_price if buying else 0),
        )
        shares = (civilians, guards, after.treasury - state.treasury)
        scales = (max(1, state.civilian_need), max(1, state.guard_need), max(1, state.treasury))
        agents = (
            Agent("residents", (0.85, 0.15, 0)),
            Agent("garrison", (0.1, 0.9, 0)),
            Agent("ruler", (0.35, 0.35, 0.3)),
        )
        result[policy] = {
            "allocation": {"civilians": civilians, "guards": guards},
            "after": asdict(after),
            "utilities": {a.id: a.utility(shares, scales) for a in agents},
            "unmet": {
                "civilians": state.civilian_need - civilians,
                "guards": state.guard_need - guards,
            },
        }
    vectors = {k: tuple(v["utilities"].values()) for k, v in result.items()}
    front = pareto_front(vectors)
    return {k: v | {"pareto": k in front} for k, v in result.items()}
