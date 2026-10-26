"""Data contracts for supported physical equipment; narration never computes its effects."""

from rpg_vkr.domain.d20_combat import ARMOUR, WEAPONS

GUIDE = (
    "\nНабор физических предметов v2: для обычного оружия используй properties.weapon "
    "из equipment_rules.weapons; damage_dice и hands, если указаны, должны совпадать "
    "с карточкой. Для брони properties.armour из equipment_rules.armour; для щита "
    "equipment_slot='shield', shield_bonus=2. Прочность durability — положительное целое, "
    "condition экземпляра от0 до durability. Не добавляй неподдержанные attack_bonus, "
    "damage_bonus или effects. Названия и описания свободны, формулы задаёт движок. "
    "Товар должен быть реальным экземпляром у торговца: ассортимент не возникает из реплики. "
    "Подключение вещи к снаряжению подтверждает игрок; не объявляй его выполненным прозой."
)


def equipment_rules():
    return {
        "weapons": {
            k: {"damage_dice": dice, "hands": hands} for k, (dice, hands) in WEAPONS.items()
        },
        "armour": [k for k in ARMOUR if k != "none"],
        "shield_bonus": 2,
    }
