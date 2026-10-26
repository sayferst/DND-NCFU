"""Small Russian/English retrieval vocabulary; never interprets a game action."""

import re

ROOTS = (
    ("осмотр", ("осматр", "осмотр", "рассмотр", "inspect")),
    ("купить", ("куп", "покуп", "buy")),
    ("продать", ("прод", "торг", "sell", "trade")),
    ("говорить", ("говор", "спрос", "ответ", "диалог", "talk")),
    ("смерть", ("смерт", "погиб", "мертв", "убит", "dead")),
    (
        "изготовить",
        (
            "изготов",
            "ремес",
            "рецепт",
            "кузн",
            "craft",
            "крафт",
            "компон",
            "материал",
            "алхим",
            "станци",
            "руда",
        ),
    ),
    ("заклинание", ("заклин", "маг", "мана", "spell")),
    ("слух", ("слух", "секрет", "тайн", "знает", "rumor")),
    ("путешествие", ("путешеств", "дорог", "переправ", "travel")),
    ("событие", ("событ", "засад", "находк", "происш", "encounter")),
    ("поведение", ("мотив", "поведен", "довер", "репутац", "фракц", "переговор", "полит")),
    ("предмет", ("предмет", "вещ", "оруж", "существ", "растен", "звер")),
    ("попытка", ("попыт", "провер", "расслед", "улик", "след", "неудач", "провал", "отдых")),
    ("обучение", ("книг", "учеб", "обуч", "изуч", "навык", "практик")),
)


def terms(text):
    words = re.findall(r"[а-яёa-z]{3,}", text.casefold().replace("ё", "е"))[:24]
    values = list(words)
    for word in words:
        for term, prefixes in ROOTS:
            if word.startswith(prefixes):
                values.append(term)
        if len(word) >= 5:
            values.append(
                re.sub(r"(?:иться|аться|овать|ить|ать|еть|ыми|ами|ого|ему|аю|ю|ы|и|а)$", "", word)
            )
    return list(dict.fromkeys(values))[:40]


def namespaces(text):
    values = set(terms(text))
    selected = {"narrative"}
    if values & {"осмотр", "слух", "говорить"}:
        selected.update(("adjudication", "behavior", "entities"))
    if "изготовить" in values or "заклинание" in values:
        selected.update(("crafting", "adjudication", "entities"))
    if values & {"купить", "продать"}:
        selected.update(("narrative", "adjudication", "entities"))
    if "смерть" in values:
        selected.update(("consequences", "behavior"))
    if "путешествие" in values:
        selected.update(("events", "entities"))
    if "событие" in values:
        selected.update(("events", "consequences"))
    if "поведение" in values:
        selected.update(("behavior", "events"))
    if "предмет" in values:
        selected.add("entities")
    if "попытка" in values:
        selected.add("adjudication")
    if "обучение" in values:
        selected.update(("crafting", "behavior"))
    return tuple(sorted(selected))
