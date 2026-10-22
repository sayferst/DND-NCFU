"""Explicit rendering requests are UI intents, never actions of the hero."""

import re


def visual_request(text):
    value = text.strip().casefold().replace("ё", "е")
    value = re.sub(r"^(?:пожалуйста[ ,]+|хочу[,]?\s+|можешь[,]?\s+|можно\s+)", "", value)
    if re.match(r"^(?:нарисуй|нарисовать|изобрази|изобразить|сгенерируй изображение)\b", value):
        return value
    if re.match(
        r"^покажи\s+(?:(?:мне|этот|эту|это|этого)\s+)*"
        r"(?:предмет|персонажа|существо|монстра|босса|изображение|портрет|картинку)\b",
        value,
    ):
        return value
    return ""


def candidate_entries(entries, query):
    if re.search(r"\b(?:персонаж|портрет|нпс)", query):
        categories = {"people"}
    elif re.search(r"\b(?:существ|монстр|босс)", query):
        categories = {"creatures"}
    elif re.search(r"\b(?:предмет|меч|оруж|доспех)", query):
        categories = {"items"}
    else:
        categories = {"people", "creatures", "items", "places"}
    choices = [e for e in entries if e.category in categories]
    named = []
    for entry in choices:
        title = entry.title.casefold().replace("ё", "е")
        if title in query:
            named.append(entry)
        elif len(title.split()) == 1 and len(title) > 4:
            stem = re.escape(title[:-2])
            if re.search(r"\b" + stem + r"\w{0,3}\b", query):
                named.append(entry)
    return named or [e for e in choices if e.here] or choices
