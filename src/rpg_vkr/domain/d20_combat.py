"""Versioned new combat arithmetic, shared by heroes and NPCs.

Legacy replay deliberately keeps its original arithmetic. This resolver must
only be attached to a new combat record format, not substituted on old saves.
"""

from dataclasses import dataclass

from rpg_vkr.domain.character import ability_modifier
from rpg_vkr.domain.dice import DiceResult, parse_expression

WEAPONS = {
    "dagger": ("1d4", 1),
    "short_sword": ("1d6", 1),
    "sword": ("1d8", 1),
    "greatsword": ("2d6", 2),
    "axe": ("1d12", 2),
    "longbow": ("1d8", 2),
    "crossbow": ("1d10", 2),
}
ARMOUR = {
    "none": (10, True),
    "leather": (11, True),
    "reinforced_leather": (12, True),
    "mail": (16, False),
    "plate": (18, False),
}


def armour_class(dexterity, armour="none", shield=False):
    if not isinstance(armour, str) or armour not in ARMOUR or type(shield) is not bool:
        raise ValueError("Неизвестный доспех или щит.")
    modifier = ability_modifier(dexterity)
    base, dex = ARMOUR[armour]
    return base + (modifier if dex else 0) + (2 if shield else 0)


@dataclass(frozen=True)
class Combatant:
    id: str
    hp: int
    max_hp: int
    attack_score: int
    dexterity: int
    weapon: str
    rank: int = 0
    armour: str = "none"
    shield: bool = False

    def __post_init__(self):
        from rpg_vkr.domain.interactions import identifier

        identifier(self.id)
        if (
            type(self.max_hp) is not int
            or not 1 <= self.max_hp <= 100000
            or type(self.hp) is not int
            or not 0 <= self.hp <= self.max_hp
            or type(self.rank) is not int
            or not 0 <= self.rank <= 5
        ):
            raise ValueError("Некорректное состояние участника боя.")
        ability_modifier(self.attack_score)
        armour_class(self.dexterity, self.armour, self.shield)
        if not isinstance(self.weapon, str) or self.weapon not in WEAPONS:
            raise ValueError("Оружие не входит в версию каталога боя.")
        if WEAPONS[self.weapon][1] == 2 and self.shield:
            raise ValueError("Двуручное оружие нельзя использовать со щитом.")


@dataclass(frozen=True)
class AttackOutcome:
    actor_id: str
    target_id: str
    hit_rolls: tuple[int, ...]
    selected_roll: int
    attack_bonus: int
    total: int
    defence: int
    hit: bool
    critical: bool
    damage_roll: DiceResult | None
    damage: int
    hp_after: int
    defeated: bool
    killed: bool
    ruleset_id: str = "dnd-ncfu-homebrew-d20-v1"
    resolver_version: str = "combat-d20-1"


def resolve_attack(actor, target, dice, *, advantage=False, disadvantage=False, lethal=False):
    if any(type(v) is not bool for v in (advantage, disadvantage, lethal)):
        raise ValueError("Режим атаки должен быть булевым.")
    if not isinstance(actor, Combatant) or not isinstance(target, Combatant):
        raise ValueError("Нужны проверенные участники боя.")
    if actor.id == target.id or actor.hp == 0 or target.hp == 0:
        raise ValueError("Атакующий или цель недоступны.")
    checkpoint = dice.checkpoint()
    try:
        rolls = (dice.roll_d20().value,)
        if advantage != disadvantage:
            rolls += (dice.roll_d20().value,)
        selected = max(rolls) if advantage and not disadvantage else min(rolls)
        bonus = ability_modifier(actor.attack_score) + 2 * actor.rank
        defence = armour_class(target.dexterity, target.armour, target.shield)
        hit = selected == 20 or selected != 1 and selected + bonus >= defence
        critical = selected == 20
        damage_roll = None
        damage = 0
        if hit:
            count, sides, _ = parse_expression(WEAPONS[actor.weapon][0])
            count *= 2 if critical else 1
            damage_roll = dice.roll(f"{count}d{sides}", reason="Урон оружия")
            damage = max(0, damage_roll.total + ability_modifier(actor.attack_score))
        hp_after = max(0, target.hp - damage)
        return AttackOutcome(
            actor.id,
            target.id,
            rolls,
            selected,
            bonus,
            selected + bonus,
            defence,
            hit,
            critical,
            damage_roll,
            damage,
            hp_after,
            hp_after == 0,
            hp_after == 0 and lethal,
        )
    except Exception:
        dice.restore(checkpoint)
        raise
