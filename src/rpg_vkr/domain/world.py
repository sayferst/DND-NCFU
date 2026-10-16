"""Authored sandbox economy and quest; these values are homebrew, not SRD tables."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.character import AbilityCheck, Character, describe_check, resolve_ability_check
from rpg_vkr.domain.dice import D20Roll, DiceRoller

LOCATIONS = {"gate": "Ворота деревни", "road": "Дорога у деревни", "market": "Рынок"}
OBSERVE_COMMANDS = {
    "осмотреться",
    "осмотреть деревню",
    "я осматриваюсь",
    "что я вижу",
    "что вокруг",
}
WHERE_COMMANDS = {"где я нахожусь", "где мы находимся"}
WORLD_COMMANDS = {
    *OBSERVE_COMMANDS,
    *WHERE_COMMANDS,
    "идти к воротам",
    "идти на дорогу",
    "идти на рынок",
    "исследовать дорогу",
    "взять поручение",
    "доставить корзину",
    "купить бинт",
    "продать бинт",
    "использовать бинт",
    "состояние",
    "инвентарь",
    "задание",
    "торговля",
    "узнать дорогу на рынок",
    "подойти к торговцу",
    "осмотреться",
    "осмотреть деревню",
    "я осматриваюсь",
    "поговорить",
    "поговорить со стражником",
    "поговорить с жительницей",
    "помочь",
    "помочь жительнице",
    "помочь собрать яблоки",
}


@dataclass(frozen=True)
class WorldState:
    location: str = "gate"
    hp: int = 12
    max_hp: int = 12
    gold: int = 10
    bandages: int = 1
    basket: int = 0
    quest: str = "available"
    explored: bool = False
    shop_stock: int = 3
    shop_gold: int = 20
    market_known: bool = False
    trading: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.location, str)
            or self.location not in LOCATIONS
            or self.quest not in ("available", "active", "completed")
        ):
            raise ValueError("Invalid world location or quest")
        limits = {
            "max_hp": (1, 1000),
            "hp": (0, self.max_hp),
            "gold": (0, 1_000_000),
            "bandages": (0, 10000),
            "basket": (0, 1),
            "shop_stock": (0, 10000),
            "shop_gold": (0, 1_000_000),
        }
        for field, (low, high) in limits.items():
            value = getattr(self, field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Invalid resource: {field}")
        if type(self.explored) is not bool or self.basket != int(self.quest == "active"):
            raise ValueError("Invalid quest inventory or exploration flag")

        if type(self.market_known) is not bool or type(self.trading) is not bool:
            raise ValueError("Invalid world knowledge")
        if self.trading and (self.location != "market" or not self.market_known):
            raise ValueError("Trade requires a known market and merchant interaction")

    @classmethod
    def from_dict(cls, data: object) -> "WorldState":
        if not isinstance(data, dict) or set(data) != set(asdict(cls())):
            raise ValueError("Invalid world structure")
        return cls(**data)


def inventory_text(state: WorldState) -> str:
    items = []
    if state.bandages:
        items.append(f"Бинт ×{state.bandages}")
    if state.basket:
        items.append("Корзина поручения ×1")
    return "; ".join(items) if items else "Пусто"


def quest_text(state: WorldState) -> str:
    return {
        "available": "Жительнице у ворот нужна помощь. Поговорите с ней, чтобы узнать о поручении.",
        "active": "Доставьте корзину на рынок. Обещанная награда — 5 золотых.",
        "completed": "Корзина доставлена, награда получена. Поручение завершено.",
    }[state.quest]


@dataclass(frozen=True)
class WorldOutcome:
    state: WorldState
    text: str
    roll: D20Roll | None = None
    check: AbilityCheck | None = None


def perform_action(
    state: WorldState, command: str, character: Character, dice: DiceRoller
) -> WorldOutcome:
    """Validate prerequisites before computing and returning a new immutable state."""
    travel = {"идти к воротам": "gate", "идти на дорогу": "road", "идти на рынок": "market"}
    if command in travel:
        destination = travel[command]
        if destination == "market" and not state.market_known:
            return WorldOutcome(
                state, "Вы ещё не знаете дорогу на рынок. Узнайте её у стражника у ворот."
            )
        if destination == state.location:
            return WorldOutcome(state, f"Вы уже здесь: {LOCATIONS[destination]}.")
        return WorldOutcome(
            replace(state, location=destination, trading=False),
            f"Вы пришли: {LOCATIONS[destination]}.",
        )
    if command in WHERE_COMMANDS:
        return WorldOutcome(state, f"Вы здесь: {LOCATIONS[state.location]}.")
    if command in OBSERVE_COMMANDS:
        description = {
            "gate": "У ворот тихо. На дороге остались следы телеги. Жительница ждёт помощи.",
            "road": "Вы на дороге. Впереди каменистый участок, рядом видна тропа в деревню.",
            "market": (
                "Вы на рынке. Видна лавка с торговцем; здесь принимают корзины. "
                "К торговцу можно подойти."
            ),
        }[state.location]
        if state.location == "road" and state.explored:
            description += " Этот участок уже исследован."
        return WorldOutcome(state, description)
    if command == "узнать дорогу на рынок":
        if state.location != "gate":
            return WorldOutcome(state, "Спросите стражника у ворот, как найти рынок.")
        return WorldOutcome(
            replace(state, market_known=True),
            "Стражник: «Рынок за площадью». Место отмечено на карте.",
        )
    if command == "поговорить с жительницей":
        if state.location != "gate":
            return WorldOutcome(state, "Жительница осталась у ворот деревни.")
        return WorldOutcome(
            state,
            "Жительница: «Нужно доставить корзину на рынок. "
            "Заплачу 5 золотых. Если согласны — возьмите поручение».",
        )
    if command == "поговорить со стражником" and state.location != "gate":
        return WorldOutcome(state, "Стражник остался у ворот деревни.")
    if command in ("поговорить", "поговорить со стражником"):
        description = {
            "gate": (
                "Стражник объясняет дорогу на рынок и советует обратиться за работой к соседке."
            ),
            "road": "Поблизости не с кем поговорить. Можно вернуться к воротам или идти на рынок.",
            "market": "Торговец занят у прилавка. Подойдите к нему, чтобы узнать ассортимент.",
        }[state.location]
        updated = replace(state, market_known=True) if state.location == "gate" else state
        return WorldOutcome(updated, description)
    if command in ("помочь", "помочь жительнице", "помочь собрать яблоки"):
        if state.location == "gate":
            return WorldOutcome(
                state,
                "Вы помогаете собрать яблоки. Жительница благодарит вас. "
                "За отдельное поручение с доставкой предусмотрена награда: взять поручение.",
            )
        return WorldOutcome(
            state, "Жительница осталась у ворот. Здесь можно осмотреться или заняться поручением."
        )
    if command == "состояние":
        return WorldOutcome(
            state,
            f"{character.name}: здоровье {state.hp}/{state.max_hp}, золото {state.gold}. "
            f"Место: {LOCATIONS[state.location]}.",
        )
    if command == "инвентарь":
        return WorldOutcome(state, inventory_text(state))
    if command == "задание":
        return WorldOutcome(state, quest_text(state))
    if command in ("торговля", "подойти к торговцу"):
        if state.location != "market":
            return WorldOutcome(
                state, "Сначала найдите рынок и придите туда, затем подойдите к торговцу."
            )
        return WorldOutcome(
            replace(state, trading=True, market_known=True),
            f"Торговец: «Бинт стоит 3 золотых, выкуп — 1». "
            f"В наличии: {state.shop_stock}. Команды: купить бинт, продать бинт.",
        )
    if command == "взять поручение":
        if state.quest != "available":
            return WorldOutcome(
                state, "Это поручение уже принято или завершено. Повторной награды нет."
            )
        if state.location != "gate":
            return WorldOutcome(state, "За поручением нужно вернуться к воротам.")
        return WorldOutcome(
            replace(state, quest="active", basket=1, market_known=True),
            "Жительница передаёт корзину, обещает 5 золотых и объясняет дорогу на рынок.",
        )
    if command == "доставить корзину":
        if state.quest != "active":
            return WorldOutcome(state, "Нет активного поручения с корзиной. Награда не выдана.")
        if state.location != "market":
            return WorldOutcome(state, "Корзину нужно доставить на рынок.")
        return WorldOutcome(
            replace(state, quest="completed", basket=0, gold=state.gold + 5),
            "Корзина доставлена. Получено 5 золотых, корзина передана получателю.",
        )
    if command == "исследовать дорогу":
        if state.location != "road":
            return WorldOutcome(state, "Сначала нужно выйти на дорогу: идти на дорогу.")
        if state.explored:
            return WorldOutcome(state, "Этот участок уже исследован. Новых находок здесь нет.")
        roll = dice.roll_d20()
        check = resolve_ability_check("dexterity", character.dexterity, roll.value, 10)
        if check.succeeded:
            updated = replace(state, explored=True, gold=state.gold + 2)
            consequence = "Вы обошли опасный участок и нашли 2 золотых."
        else:
            damage = min(3, state.hp)
            updated = replace(state, explored=True, hp=state.hp - damage)
            consequence = f"Вы поскользнулись. Потеряно здоровья: {damage}."
        return WorldOutcome(
            updated, describe_check(check, roll.value) + "\n" + consequence, roll, check
        )
    if command in ("купить бинт", "продать бинт"):
        if state.location != "market":
            return WorldOutcome(state, "Лавка находится на рынке: идти на рынок.")
        if not state.trading:
            return WorldOutcome(state, "Сначала подойдите к торговцу и узнайте его ассортимент.")
        if command == "купить бинт":
            if state.gold < 3 or not state.shop_stock:
                return WorldOutcome(
                    state, "Покупка невозможна: недостаточно золота или нет товара."
                )
            return WorldOutcome(
                replace(
                    state,
                    gold=state.gold - 3,
                    bandages=state.bandages + 1,
                    shop_stock=state.shop_stock - 1,
                    shop_gold=state.shop_gold + 3,
                ),
                "Куплен бинт за 3 золотых.",
            )
        if not state.bandages or not state.shop_gold:
            return WorldOutcome(
                state,
                "У вас нет бинта для продажи."
                if not state.bandages
                else "Торговец отказывается: сейчас не готов выкупить ваш бинт.",
            )
        return WorldOutcome(
            replace(
                state,
                gold=state.gold + 1,
                bandages=state.bandages - 1,
                shop_stock=state.shop_stock + 1,
                shop_gold=state.shop_gold - 1,
            ),
            "Продан бинт за 1 золотой.",
        )
    if command == "использовать бинт":
        if state.hp == state.max_hp:
            return WorldOutcome(state, "Здоровье полное. Бинт не потрачен.")
        if not state.bandages:
            return WorldOutcome(state, "В инвентаре нет бинтов.")
        healing = min(4, state.max_hp - state.hp)
        return WorldOutcome(
            replace(state, hp=state.hp + healing, bandages=state.bandages - 1),
            f"Использован бинт. Восстановлено здоровья: {healing}.",
        )
    raise ValueError("Unknown world command")
