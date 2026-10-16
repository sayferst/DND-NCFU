"""Shared author-rule arithmetic for the engine and its read-only explanations."""

from dataclasses import dataclass

from rpg_vkr.domain.character import ability_modifier


@dataclass(frozen=True)
class DamageCalculation:
    weapon: int
    strength: int
    bonus: int
    multiplier: int = 1

    @property
    def base(self) -> int:
        return self.weapon + self.strength

    @property
    def total(self) -> int:
        return (self.base + self.bonus) * self.multiplier


def player_damage(weapon: int, strength_score: int, die: int, surprise: bool):
    return DamageCalculation(
        weapon, max(0, ability_modifier(strength_score)), (die - 1) // 5, 2 if surprise else 1
    )


def counter_damage(base: int, die: int):
    return DamageCalculation(base, 0, (die - 1) // 10)


def hero_defence(dexterity: int):
    return 10 + max(0, ability_modifier(dexterity))
