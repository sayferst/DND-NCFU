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


FACTION_GUIDE = (
    "\nЕсли это уместно миру, существующие NPC могут иметь публичную принадлежность: "
    "properties.faction_id (стабильный ID), faction_name (имя), faction_goal "
    "(security или prosperity). У одной фракции одно имя и цель. "
    "Не назначай её деньги/влияние/репутацию: начальные ресурсы и суточные действия "
    "считает движок. Не добавляй фракции в одиночный/пустой мир ради списка. "
    "Слух, услышанный NPC, не становится личным наблюдением или раскрытым секретом."
)


TEAM_GUIDE = """
Для Приключения v3 revision4 используется общая очередь инициативы: герой и до7 NPC.
NPC может иметь properties.party_ally=true только при обоснованном согласии помогать,
а его state.disposition должно быть friendly. Это возможность вступить в бой, не
автоматическое участие. Состав обеих сторон выбирает игрок. Числа инициативы,
ходы, попадания, ST и последствия назначает движок; не создавай их повествованием.
"""
