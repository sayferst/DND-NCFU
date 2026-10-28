"""Readable witnessed world events; no raw catalog titles or private state."""

MESSAGES = {
    "production": "Жители приготовили пищу из трав.",
    "office": "Житель получил новое занятие.",
    "apprentice": "Житель приступил к обучению ремеслу.",
    "share_food": "Жители поделились запасами пищи.",
    "maintenance": "Жители израсходовали припасы на помощь пострадавшему.",
    "assist": "Пострадавшему оказали помощь.",
    "rescue": "Пострадавшему оказали помощь.",
    "wage": "За работу выплачено жалованье.",
    "commission": "Из казны оплачена работа.",
    "aid": "Жителю выплачена помощь из казны.",
    "levy": "В казну поступил взнос.",
    "closure": "Одна из местных лавок временно закрылась.",
    "embargo": "Местная торговля временно ограничена.",
    "celebrate": "Жители устроили праздник за свой счёт.",
    "raid": "Между жителями произошла стычка.",
    "dispute": "Между жителями возник спор.",
    "treaty": "Жители улучшили отношения.",
    "truce": "Жители договорились о перемирии.",
    "cooperate": "Жители договорились о сотрудничестве.",
    "shipment_arrived": "В поселение прибыла настоящая поставка.",
    "shipment_delayed": "Поставка задерживается из-за закрытой дороги.",
    "resident_born": "В поселении появился ребёнок.",
    "resident_died": "Житель поселения погиб от голода.",
}


def labels(world, current):
    result = []
    for event in world.get("observed", {}).get(current, [])[-10:]:
        text = MESSAGES.get(event.get("operation", event.get("kind")))
        if text and (not result or result[-1] != text):
            result.append(text)
    return result[-2:]
