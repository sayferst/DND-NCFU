"""Owner rules revision1: pure math shared by runtime and synthetic-data verification.

R06/R08/R10/R14 are homebrew. Death saves/exhaustion follow SRD5.2.1.
No item names, natural-language phrases, sample IDs or model-generated resources.
"""

from dataclasses import asdict, dataclass, replace
from math import ceil

VERSION = "owner-rules-1"


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid " + name)
    return value


@dataclass(frozen=True)
class Life:
    hp: int
    maximum: int
    exhaustion: int = 0
    dead: bool = False
    stable: bool = False
    successes: int = 0
    failures: int = 0
    knocked_out: bool = False

    def __post_init__(self):
        integer(self.maximum, 1, 1000000, "maximum HP")
        integer(self.hp, 0, self.maximum, "HP")
        integer(self.exhaustion, 0, 6, "exhaustion")
        integer(self.successes, 0, 2, "death successes")
        integer(self.failures, 0, 3, "death failures")
        for value in (self.dead, self.stable, self.knocked_out):
            if type(value) is not bool:
                raise ValueError("Life flags must be Boolean")
        if self.dead and (self.hp or self.stable or self.successes):
            raise ValueError("Dead creature cannot have HP or be stable")
        if self.hp and (self.stable or self.successes or self.failures):
            raise ValueError("Positive HP resets stabilization and death counters")
        if self.stable and (self.successes or self.failures):
            raise ValueError("Stabilization resets death counters")
        if self.exhaustion == 6 and not self.dead:
            raise ValueError("Six exhaustion levels cause death")
        if self.failures == 3 and not self.dead:
            raise ValueError("Three failed death saves cause death")

    @property
    def unconscious(self):
        return not self.dead and (self.hp == 0 or self.knocked_out)

    def public(self):
        return asdict(self) | {"unconscious": self.unconscious}


def heal(life, amount):
    integer(amount, 0, 1000000, "healing")
    if life.dead or amount == 0:
        return life
    return replace(
        life,
        hp=min(life.maximum, life.hp + amount),
        stable=False,
        successes=0,
        failures=0,
        knocked_out=False,
    )


def stabilize(life):
    if life.dead or life.hp != 0:
        raise ValueError("Only a living creature at0HP can be stabilized")
    return replace(life, stable=True, successes=0, failures=0)


def damage(life, amount, *, critical=False, nonlethal=False, knockout_hp=0):
    integer(amount, 0, 1000000, "damage")
    if type(critical) is not bool or type(nonlethal) is not bool:
        raise ValueError("Damage flags must be Boolean")
    if amount == 0 or life.dead:
        return life
    if nonlethal and life.hp > 0 and amount >= life.hp:
        integer(knockout_hp, 0, 1, "knockout HP")
        return replace(
            life, hp=knockout_hp, stable=knockout_hp == 0, successes=0, failures=0, knocked_out=True
        )
    if amount >= life.hp + life.maximum:
        return replace(life, hp=0, dead=True, stable=False, successes=0, knocked_out=False)
    if life.hp == 0:
        failures = min(3, life.failures + (2 if critical else 1))
        return replace(
            life,
            stable=False,
            failures=failures,
            successes=0 if failures == 3 else life.successes,
            dead=failures == 3,
        )
    return replace(
        life, hp=max(0, life.hp - amount), stable=False, successes=0, failures=0, knocked_out=False
    )


def death_save(life, natural):
    integer(natural, 1, 20, "D20")
    if life.dead or life.hp or life.stable:
        raise ValueError("A death save requires an unstable living creature at0HP")
    if natural == 20:
        return heal(life, 1)
    success = natural - 2 * life.exhaustion >= 10
    successes = life.successes + int(success)
    failures = min(3, life.failures + (2 if natural == 1 else int(not success)))
    if failures == 3:
        return replace(life, dead=True, stable=False, successes=0, failures=3)
    if successes == 3:
        return stabilize(life)
    return replace(life, successes=successes, failures=failures)


def add_exhaustion(life, levels):
    integer(levels, 0, 6, "exhaustion cost")
    if life.dead:
        return life
    level = min(6, life.exhaustion + levels)
    if level == 6:
        return replace(
            life,
            hp=0,
            exhaustion=6,
            dead=True,
            stable=False,
            successes=0,
            failures=0,
            knocked_out=False,
        )
    return replace(life, exhaustion=level)


def long_rest(life):
    if life.dead or life.hp < 1:
        raise ValueError("A long rest must start alive with at least1HP")
    # Completion eligibility (duration, interruptions, food hazards) is a runtime check.
    return replace(life, hp=life.maximum, exhaustion=max(0, life.exhaustion - 1), knocked_out=False)


def speed(life, base_feet):
    integer(base_feet, 0, 1000, "base speed")
    return 0 if life.dead or life.unconscious else max(0, base_feet - 5 * life.exhaustion)


def check(natural, modifier, dc, *, exhaustion=0, partial=True, goal_possible=True):
    integer(dc, 1, 30, "DC")
    integer(modifier, -100, 100, "modifier")
    integer(exhaustion, 0, 5, "exhaustion")
    if not goal_possible:
        return {
            "natural": None,
            "total": None,
            "dc": None,
            "succeeded": False,
            "outcome": "goal_unreachable",
            "complication": False,
        }
    integer(natural, 1, 20, "D20")
    total = natural + modifier - 2 * exhaustion
    succeeded = natural == 20 or total >= dc
    outcome = (
        "best_possible"
        if natural == 20
        else "success_with_complication"
        if succeeded and natural == 1
        else "success"
        if succeeded
        else "partial_success"
        if partial and total >= dc - 5
        else "failure"
    )
    return {
        "natural": natural,
        "total": total,
        "dc": dc,
        "succeeded": succeeded,
        "outcome": outcome,
        "complication": natural == 1,
    }


def overcast(life, available_mp, spell_cost, payment, *, allow_partial_hp=False):
    integer(available_mp, 0, 1000000, "available MP")
    integer(spell_cost, 1, 1000000, "spell MP cost")
    missing = max(0, spell_cost - available_mp)
    if life.dead or life.unconscious or not 1 <= missing <= 3:
        raise ValueError("Overcast needs a conscious caster and1–3 missing MP")
    record = {
        "missing_mp": missing,
        "dc": 10 + 2 * missing,
        "payment": payment,
        "mp_spent": available_mp,
        "hp_spent": 0,
        "exhaustion_added": 0,
    }
    if payment == "hp":
        price = 2 * missing
        if life.hp < price and not allow_partial_hp:
            raise ValueError("Insufficient HP; choose an explicit alternative payment")
        record.update(hp_price=price, hp_spent=min(price, life.hp))
        life = replace(life, hp=max(0, life.hp - price), stable=False, successes=0, failures=0)
    elif payment == "exhaustion":
        levels = ceil(missing / 2)
        record["exhaustion_added"] = levels
        life = add_exhaustion(life, levels)
    else:
        raise ValueError("Choose HP or exhaustion explicitly")
    return life, record


def agreement_eligibility(*, authority, feasible, constraints):
    if authority is None or feasible is None or constraints is None:
        return "clarification_required"
    if (
        type(authority) is not bool
        or type(feasible) is not bool
        or not isinstance(constraints, list)
    ):
        raise ValueError("Agreement facts must be explicit")
    if any(value is None for value in constraints):
        return "clarification_required"
    if any(type(value) is not bool for value in constraints):
        raise ValueError("Vital constraints must be explicit Boolean facts")
    return (
        "eligible"
        if authority and feasible and all(constraints)
        else "outside_authority_or_vital_limits"
    )
