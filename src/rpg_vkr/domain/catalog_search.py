"""Small deterministic intent index. Selection is never permission to execute an action."""

import re

STOP = {"хочу", "нужно", "мне", "пожалуйста", "применить", "изучить", "заклинание", "рецепт"}
LEXICON = {
    "fire": "огонь огненный пламя поджечь обжечь горение",
    "cold": "лёд ледяной заморозить холод мороз",
    "heal": "исцелить лечить лечение рана здоровье",
    "restore_mp": "восстановить мана магия запас",
    "restore_st": "выносливость усталость дыхание силы",
    "reveal_routes": "дорога маршрут тропа проход путь найти",
    "reveal_items": "найти предмет вещь спрятанный поиск",
    "reveal_actors": "обнаружить существо жизнь зверь разведка",
    "repair": "починить ремонт вещь снаряжение",
    "light": "осветить свет темнота фонарь освещение",
    "conceal": "спрятаться скрытность тень маскировка",
    "dispel": "рассеять снять чары иллюзия",
    "shield": "защита щит поглощение прикрыть",
    "slow": "замедлить путы задержать остановить",
    "direct": "обычный прямой одиночный",
    "reach": "далеко дальний расстояние",
    "area": "область площадь группа массовый",
    "sustained": "поддерживать поддерживаемый длительный",
    "ritual": "ритуал спокойно подготовить",
}


def words(text):
    found = []
    for word in re.findall(r"[а-яa-z]+", text.casefold().replace("ё", "е")):
        if word in STOP or len(word) < 3:
            continue
        word = re.sub(
            r"(?:иями|иями|ение|ения|ыми|ими|ого|ому|ами|ями|ать|ить|ять|ете|ите|ая|яя|ые|ие|ий|ый|ой|ую|юю|ом|ем|ам|ям|ов|ев|ы|и|а|я|у|ю|е|о|ь)$",
            "",
            word,
        )
        found.append(word)
    return set(found)


def ranked(rows, query, *, limit=None, matching_only=False):
    terms = words(query)
    scores = []
    for row in rows:
        name = row["name"].casefold().replace("ё", "е")
        keys = [row.get("element", ""), row.get("mode", "")]
        keys += [e["op"] for e in row.get("effects", [])]
        extra = " ".join(LEXICON.get(k, "") for k in keys)
        direct, semantic = words(name), words(extra)
        score = 12 * len(terms & direct) + 4 * len(terms & semantic)
        if query.strip() and name in query.casefold().replace("ё", "е"):
            score += 1000
        if not matching_only or not terms or score:
            scores.append((score, row["id"], row))
    scores.sort(key=lambda entry: (-entry[0], entry[1]))
    return [r for _, _, r in scores[:limit]]
