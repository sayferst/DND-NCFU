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

NPC_WORLD_GUIDE = """
Профессия NPC задаётся properties.class: smith, forester, farmer, weaver, hunter,
quarrier, miner, glassmaker, alchemist, artisan; для торговли merchant/trader/shopkeeper.
Обычный житель — resident, охранник — guard. Придерживайся выбранного мира: профессии
не обязательный список персонажей. home_place/workplace могут ссылаться только на
существующие места. NPC перемещаются по дорогам, питаются и расходуют реальные запасы.
Работа требует настоящих инструментов и станции. Пример инструментов: определение
kind='item', properties.game_template_id='house_0_0'; экземпляр parent_id=ID NPC,
owner_id=тот же ID. Это его вещь, не награда герою. Для общественного верстака:
properties.station='workbench', public=true; аналогично forge/alchemy при необходимости.
Не назначай готовые результаты производства или доходы: их вычисляет движок.
Согласившийся союзник может иметь properties.party_ally=true и state.disposition='friendly'.
Это разрешает выбор в команду, но не включает его автоматически. Фракция задаётся
faction_id/faction_name/faction_goal (security/prosperity), без выдуманной казны и репутации.
"""
