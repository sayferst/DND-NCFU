"""Small explicit conversational grammar, not arbitrary natural-language understanding."""

import re

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.combat import ACTORS

ADDRESSEES = {"жительница": "villager", "стражник": "guard", "торговец": "merchant"}
QUESTIONS = {
    "чем занята": "occupation_female",
    "яем занята": "occupation_female",  # Reported typo; no general fuzzy command matching.
    "чем занят": "occupation",
    "чем занимаешься": "occupation",
    "что случилось": "occupation",
    "чем могу помочь": "help",
    "как пройти на рынок": "directions",
    "где рынок": "directions",
    "что продаешь": "wares",
    "что у тебя есть": "wares",
    "сколько стоит бинт": "wares",
}


def dialogue_intent(action):
    text = normalise_action(action).replace("ё", "е")
    target = None
    match = re.fullmatch(r"(жительница|стражник|торговец)\s*[:,]\s*(.+)", text)
    if match:
        target, text = ADDRESSEES[match[1]], match[2]
    text = re.sub(r"^(привет|здравствуй|здравствуйте)(?:\s*[,!.?]\s*|\s+|$)", "", text)
    if not text and action.strip(".!? \t\n"):
        return target, "greeting"
    topic = QUESTIONS.get(text)
    return (target, topic) if topic else None


def dialogue_reply(session, intent):
    """Return speaker/text/identity without changing state, knowledge or RNG."""
    target, topic = intent
    location = session.world.location
    if target is None:
        if topic == "occupation_female":
            target = "villager"
        elif topic == "wares":
            target = "merchant"
        elif topic == "directions":
            target = "guard"
        elif session.turns and session.turns[-1].actor_id in ADDRESSEES.values():
            target = session.turns[-1].actor_id
        elif location == "market":
            target = "merchant"
    if target is None or ACTORS[target][1] != location:
        return (
            "Рассказчик",
            (
                "Уточните, к кому обращаетесь: «жительница, чем занята?» или "
                "«стражник, привет». Собеседник должен находиться рядом."
            ),
            None,
        )
    name = ACTORS[target][0]
    actor = session.combat.actor(target)
    if actor.hp == 0 or actor.disposition == "hostile":
        return (
            name,
            f"{name}: мирное взаимодействие недоступно — "
            + ("персонаж повержен." if actor.hp == 0 else "персонаж враждебен."),
            target,
        )
    if topic == "directions":
        text = "Чтобы отметить путь на карте, спросите: «узнать дорогу на рынок»."
    elif target == "villager":
        text = {
            "available": (
                "Нужно доставить корзину на рынок. Заплачу 5 золотых. "
                "Если согласны, напишите: «взять поручение»."
            ),
            "active": "Вы уже взяли мою корзину. Доставьте её на рынок.",
            "completed": "Спасибо за доставку корзины. Новых поручений у меня пока нет.",
        }[session.world.quest]
        if topic == "greeting":
            text = "Здравствуйте. " + text
    elif target == "merchant":
        if not session.world.trading:
            text = "Здравствуйте. Подойдите к прилавку: «подойти к торговцу», и обсудим товары."
        else:
            from rpg_vkr.domain.world import perform_action

            # Same public offer and finite stock as the existing shop, never a second price list.
            text = (
                perform_action(session.world, "торговля", session.character, session.dice)
                .text.removeprefix("Торговец: ")
                .strip("«».")
            )
    else:
        text = "Здравствуйте. Я наблюдаю за дорогой. У соседки можно спросить о работе."
    return name, f"{name}: «{text}»", target
