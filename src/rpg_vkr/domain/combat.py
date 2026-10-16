"""Small original combat rules; these are not SRD monster stat blocks or combat."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.character import (
    AbilityCheck,
    Character,
    resolve_ability_check,
)
from rpg_vkr.domain.combat_math import counter_damage, hero_defence, player_damage
from rpg_vkr.domain.dice import D20Roll, DiceRoller
from rpg_vkr.domain.world import WorldState

RULES_VERSION = "homebrew-combat-1"
# name, location, HP, defence, attack modifier, damage base, initial disposition
ACTORS = {
    "guard": ("Стражник", "gate", 18, 12, 2, 2, "neutral"),
    "villager": ("Жительница", "gate", 8, 9, 0, 1, "neutral"),
    "merchant": ("Торговец", "market", 12, 10, 1, 1, "neutral"),
    "wolf": ("Серый волк", "road", 10, 10, 1, 1, "hostile"),
    "boar": ("Кабан", "road", 12, 10, 1, 2, "neutral"),
}
NAMES_TO_IDS = {spec[0]: key for key, spec in ACTORS.items()}
ATTACK_COMMANDS = {
    "атаковать стражника": "guard",
    "атаковать жительницу": "villager",
    "атаковать торговца": "merchant",
    "атаковать волка": "wolf",
    "атаковать кабана": "boar",
}
ANGER_COMMANDS = {
    "поссориться со стражником": "guard",
    "поссориться с жительницей": "villager",
    "поссориться с торговцем": "merchant",
    "спровоцировать кабана": "boar",
}
STEALTH_COMMANDS = {"подкрасться к волку": "wolf", "подкрасться к кабану": "boar"}
COMBAT_COMMANDS = {
    *ATTACK_COMMANDS,
    *ANGER_COMMANDS,
    *STEALTH_COMMANDS,
    "атаковать",
    "уклониться",
    "отступить",
}
WEAPON_BASE = {"legacy": 1, "fighter": 3, "scout": 2, "scholar": 1}


@dataclass(frozen=True)
class ActorState:
    id: str
    hp: int
    disposition: str

    def __post_init__(self):
        if not isinstance(self.id, str) or self.id not in ACTORS:
            raise ValueError("Unknown actor")
        if type(self.hp) is not int or not 0 <= self.hp <= ACTORS[self.id][2]:
            raise ValueError("Invalid actor health")
        if self.disposition not in ("neutral", "hostile"):
            raise ValueError("Invalid disposition")


@dataclass(frozen=True)
class CombatState:
    actors: tuple[ActorState, ...] = tuple(
        ActorState(key, spec[2], spec[6]) for key, spec in ACTORS.items()
    )
    active: str | None = None
    surprise: bool = False
    rounds: int = 0

    def __post_init__(self):
        if tuple(actor.id for actor in self.actors) != tuple(ACTORS):
            raise ValueError("Invalid actor roster")
        if (
            type(self.surprise) is not bool
            or type(self.rounds) is not int
            or not 0 <= self.rounds <= 2000
        ):
            raise ValueError("Invalid combat context")
        if self.active is not None:
            actor = self.actor(self.active)
            if actor.hp == 0 or (actor.disposition != "hostile" and not self.surprise):
                raise ValueError("Invalid active opponent")
        elif self.surprise:
            raise ValueError("Surprise requires an encounter")

    def actor(self, actor_id: str) -> ActorState:
        return (
            next((actor for actor in self.actors if actor.id == actor_id), None) or self._unknown()
        )

    @staticmethod
    def _unknown():
        raise ValueError("Unknown actor")

    def update(self, actor: ActorState, **context):
        return replace(
            self,
            actors=tuple(actor if old.id == actor.id else old for old in self.actors),
            **context,
        )

    def to_dict(self):
        result = asdict(self)
        result["actors"] = [asdict(actor) for actor in self.actors]
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {"actors", "active", "surprise", "rounds"}:
            raise ValueError("Invalid combat state")
        if not isinstance(data["actors"], list) or len(data["actors"]) != len(ACTORS):
            raise ValueError("Invalid actor list")
        actors = []
        for item in data["actors"]:
            if not isinstance(item, dict) or set(item) != {"id", "hp", "disposition"}:
                raise ValueError("Invalid actor data")
            actors.append(ActorState(**item))
        if data["active"] is not None and not isinstance(data["active"], str):
            raise ValueError("Invalid active target")
        return cls(tuple(actors), data["active"], data["surprise"], data["rounds"])


@dataclass(frozen=True)
class CombatOutcome:
    state: CombatState
    world: WorldState
    text: str
    actor_id: str | None
    rolls: tuple[D20Roll, ...] = ()
    check: AbilityCheck | None = None
    victory: bool = False


def disposition_label(actor: ActorState) -> str:
    female = actor.id == "villager"
    if actor.hp == 0:
        return "Повержена" if female else "Повержен"
    if actor.disposition == "hostile":
        return "Враждебна" if female else "Враждебен"
    return "Нейтральна" if female else "Нейтрален"


def health_description(actor: ActorState) -> str:
    maximum = ACTORS[actor.id][2]
    if actor.hp == 0:
        return "повержена" if actor.id == "villager" else "повержен"
    if actor.hp == maximum:
        return "без видимых ран"
    if actor.id == "villager":
        return "тяжело ранена" if actor.hp * 2 <= maximum else "ранена"
    return "тяжело ранен" if actor.hp * 2 <= maximum else "ранен"


def perform_combat(
    state: CombatState,
    world: WorldState,
    character: Character,
    class_id: str,
    command: str,
    dice: DiceRoller,
) -> CombatOutcome:
    if state.active is not None and (world.hp == 0 or ACTORS[state.active][1] != world.location):
        raise ValueError("Active encounter context mismatch")
    if class_id not in WEAPON_BASE:
        raise ValueError("Unknown combat profile")
    actor_id = (
        ATTACK_COMMANDS.get(command)
        or ANGER_COMMANDS.get(command)
        or STEALTH_COMMANDS.get(command)
        or state.active
    )

    def blocked(text):
        return CombatOutcome(state, world, text, actor_id)

    if world.hp == 0:
        return blocked("Вы выбыли из схватки. Загрузите сохранение или создайте нового героя.")
    if actor_id is None:
        return blocked("Нет активного противника. Сначала выберите цель в текущем месте.")
    target = state.actor(actor_id)
    name, location, _, defence, attack_bonus, enemy_base, _ = ACTORS[actor_id]
    if world.location != location:
        return blocked("Цель находится в другом месте. Действие не выполнено.")
    if not target.hp:
        return blocked(f"{name} уже повержен. Повторной победы и награды нет.")
    if state.active is not None and state.active != actor_id:
        return blocked("Сначала завершите текущую схватку или отступите.")
    if command in ANGER_COMMANDS:
        if target.disposition == "hostile":
            return blocked(f"{name} уже враждебен.")
        target = replace(target, disposition="hostile")
        return CombatOutcome(
            state.update(target),
            replace(world, trading=False) if actor_id == "merchant" else world,
            "Провокация вызвала агрессию. Мирное общение с целью недоступно.",
            actor_id,
        )
    rolls = []

    def roll():
        result = dice.roll_d20()
        rolls.append(result)
        return result

    text = []
    check = None
    updated = state
    if command in STEALTH_COMMANDS:
        if state.active is not None:
            return blocked("В открытой схватке скрытно подойти заново нельзя.")
        approach = roll()
        check = resolve_ability_check("dexterity", character.dexterity, approach.value, 15)
        if check.total >= 15:
            detail = (
                "очень удачно — цель вас не заметила; "
                "следующая попытка атаки получает ×2 к урону при попадании"
            )
        elif check.total >= 10:
            detail = "удачно — вас заметили в конце подхода, скрытый удар потерян"
        elif check.total >= 5:
            detail = "малоудачно — вас заметили в середине подхода"
        else:
            detail = "неудачно — вас заметили в начале подхода"
        text.append(
            f"Подход: d20 ({approach.value}) {check.modifier:+d} = {check.total}; {detail}."
        )
        updated = state.update(
            target if check.total >= 15 else replace(target, disposition="hostile"),
            active=actor_id,
            surprise=check.total >= 15,
            rounds=state.rounds + 1,
        )
        if check.total >= 15:
            return CombatOutcome(updated, world, "\n".join(text), actor_id, tuple(rolls), check)
    elif command in ATTACK_COMMANDS or command == "атаковать":
        hit = roll()
        check = resolve_ability_check("strength", character.strength, hit.value, defence)
        target = replace(target, disposition="hostile")
        text.append(
            f"Попадание: d20 ({hit.value}) {check.modifier:+d} = {check.total} — "
            + ("попали." if check.succeeded else "промах.")
        )
        if check.succeeded:
            power = roll()
            calculation = player_damage(
                WEAPON_BASE[class_id], character.strength, power.value, state.surprise
            )
            base, bonus, multiplier = calculation.base, calculation.bonus, calculation.multiplier
            damage = calculation.total
            target = replace(target, hp=max(0, target.hp - damage))
            text.append(
                f"Расчётный урон: база {base} + бонус {bonus} (d20 {power.value}), "
                f"множитель ×{multiplier} = {damage}."
            )
        updated = state.update(
            target, active=actor_id if target.hp else None, surprise=False, rounds=state.rounds + 1
        )
        world = replace(world, trading=False) if actor_id == "merchant" else world
        if not target.hp:
            text.append(f"{name} повержен. Схватка завершена.")
            return CombatOutcome(
                updated, world, "\n".join(text), actor_id, tuple(rolls), check, True
            )
    elif command == "использовать бинт":
        if world.bandages == 0 or world.hp == world.max_hp:
            return blocked("Бинт не использован: нет бинта или здоровье полное. Ход не потрачен.")
        healed = min(4, world.max_hp - world.hp)
        world = replace(world, hp=world.hp + healed, bandages=world.bandages - 1)
        updated = state.update(
            replace(target, disposition="hostile"), rounds=state.rounds + 1, surprise=False
        )
        text.append(f"Бинт восстановил {healed} здоровья. Противник отвечает.")
    elif command in ("уклониться", "отступить"):
        evade = roll()
        check = resolve_ability_check("dexterity", character.dexterity, evade.value, 10)
        text.append(
            f"Манёвр: d20 ({evade.value}) {check.modifier:+d} = {check.total} — "
            + ("успех." if check.succeeded else "неудача.")
        )
        updated = state.update(
            replace(target, disposition="hostile"), surprise=False, rounds=state.rounds + 1
        )
        if check.succeeded:
            if command == "отступить":
                updated = state.update(target, active=None, surprise=False, rounds=state.rounds + 1)
                text.append("Вы разорвали дистанцию. Отношение цели не изменилось.")
            else:
                text.append("Вы избежали ответной атаки, но сами не атаковали.")
            return CombatOutcome(updated, world, "\n".join(text), actor_id, tuple(rolls), check)
    else:
        raise ValueError("Unsupported combat command")
    counter = roll()
    defence_value = hero_defence(character.dexterity)
    hit_back = counter.value + attack_bonus >= defence_value
    text.append(
        f"{name} отвечает: d20 ({counter.value}) {attack_bonus:+d} — "
        + ("попадание." if hit_back else "промах.")
    )
    if hit_back:
        power = roll()
        damage = counter_damage(enemy_base, power.value).total
        lost = min(world.hp, damage)
        world = replace(world, hp=world.hp - lost)
        text.append(f"Потеря здоровья: {lost} (расчётный урон {damage}, d20 {power.value}).")
    if world.hp == 0:
        updated = replace(updated, active=None, surprise=False)
        text.append(
            "Вы выбыли из схватки. Дальнейшие действия заблокированы до загрузки или нового героя."
        )
    return CombatOutcome(updated, world, "\n".join(text), actor_id, tuple(rolls), check)
