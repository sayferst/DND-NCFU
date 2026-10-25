"""Contextual conversation intent. Identity comes from the scene, never a fixed quest."""

import hashlib
import re

from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.narrative.speech import explicit_target, speech_details

NAMES = {
    "villager": ("Алина", "Марта", "Велена", "Дарина", "Таисия", "Лада", "Мила", "Ярина"),
    "guard": ("Арсен", "Борис", "Гордей", "Ратмир", "Савелий", "Тихон", "Фрол", "Яромир"),
    "merchant": ("Аким", "Влас", "Демьян", "Елисей", "Клим", "Лавр", "Мирон", "Прохор"),
}
TOPICS = {
    "wellbeing": r"как.{0,30}(?:дела|пожива|самочувств|чувству)|все ли.{0,12}порядке",
    "help": r"помощ|помочь|поручен|помо[гж]|что случилось",
    "name": r"\bимя\b|\bзовут\b|\bпредстав\w*|как.{0,15}звать",
}
TASKS = {
    "wellbeing": "Отреагируй на вопрос о самочувствии с учётом обстоятельств NPC.",
    "help": "NPC оценивает предложение помощи; это ещё не согласие героя на поручение.",
    "name": "Используй сохранённое имя; NPC может представиться или обоснованно скрыть имя.",
    "occupation": "Ответ связан с занятием и целями говорящего.",
    "appearance": "Опиши наблюдаемую внешность без повторной панорамы.",
    "background": "Происхождение раскрывай только в пределах знаний говорящего.",
    "directions": "Объясни известный путь; неизвестный не выдавай за подтверждённый.",
    "wares": "Обсуди существующие товары; разговор ещё не выполняет оплату.",
}


def name_forms(name):
    value = name.casefold().replace("ё", "е")
    if value.endswith("ия"):
        return {value, value[:-2] + "ии", value[:-2] + "ию", value[:-2] + "ией"}
    if value.endswith("а"):
        return {value, *(value[:-1] + end for end in ("ы", "и", "е", "у", "ой"))}
    if value.endswith(("й", "ь")):
        return {value, *(value[:-1] + end for end in ("я", "ю", "ем", "е"))}
    return {value, *(value + end for end in ("а", "у", "ом", "е"))}


def scene_roster(frame, campaign=None):
    campaign = campaign or {}
    if "actors" in campaign:
        return [a for a in campaign["actors"] if a.get("available", True)]
    result = []
    for line in frame.visible_actors:
        name = line.split(":", 1)[0]
        id = next((key for key, spec in ACTORS.items() if spec[0] == name), None)
        if id:
            result.append(
                {
                    "id": id,
                    "name": name,
                    "available": ": погиб" not in line and ": повержен" not in line,
                }
            )
    return [a for a in result if a["available"]]


def mentioned_actors(text, actors):
    normal = text.casefold().replace("ё", "е")
    return [
        a["id"]
        for a in actors
        if any(
            re.search(r"\b" + re.escape(form) + r"\b", normal)
            for name in (a["name"], *a.get("aliases", []))
            for token in name.split()
            if len(token) > 2
            for form in name_forms(token)
        )
    ]


def turn_brief(frame, text, *, campaign=None, memory=None, master=False):
    campaign, memory = campaign or {}, memory or {}
    normal = text.casefold().replace("ё", "е")
    actors = scene_roster(frame, campaign)
    visible = [a["id"] for a in actors]
    names = {
        f["subject"]: f["value"]
        for f in memory.get("facts", ())
        if f.get("key") == "public_name" and f.get("subject") in visible
    }
    aliases = [
        {**a, "aliases": [*a.get("aliases", []), names[a["id"]]]} if a["id"] in names else a
        for a in actors
    ]
    matched = mentioned_actors(text, aliases)
    target = matched[0] if len(matched) == 1 else explicit_target(text)
    if target not in visible:
        target = None
    preferred = campaign.get("requested_target")
    if not target and preferred in visible:
        target = preferred
    topics = [key for key, pattern in TOPICS.items() if re.search(pattern, normal)]
    act, topic = speech_details(text)
    world_question = master or bool(
        re.search(
            r"\b(?:что (?:я )?вижу|что видно|что слышно|где (?:я|мы)|осматри|осмотр|касаюсь)\b",
            normal,
        )
    )
    if topic in TASKS and topic not in topics and topic != "help":
        topics.append(topic)
    spatial = bool(re.search(r"\b(?:к воротам|на рынок|на дорогу|в ворота)\b", normal))
    approach = not spatial and bool(re.search(r"\b(?:подойду|подойти|подхожу)\b", normal))
    social = bool(
        target
        or re.search(r"\b(?:ты|тебя|тебе|вас|вам)\b|спро|спраш|поговор", normal)
        or approach
        or act in {"greeting", "farewell", "refusal", "apology", "insult", "threat"}
    )
    if not target and social and not world_question:
        previous = campaign.get("interlocutor_id")
        if previous in visible:
            target = previous
        else:
            feminine = bool(re.search(r"\b(?:она|ей|ней|нее)\b", normal))
            masculine = bool(re.search(r"\b(?:он|ему|ним|него)\b", normal))
            candidates = [
                a["id"]
                for a in actors
                if not (feminine or masculine)
                or (a.get("gender") == "female" or a["name"].casefold().endswith(("а", "я")))
                == feminine
            ]
            if len(candidates) == 1:
                target = candidates[0]
    clarification = ""
    if social and not target and not world_question:
        clarification = (
            "К кому вы обращаетесь: " + ", ".join(a["name"] for a in actors) + "?"
            if actors
            else "Рядом нет доступного собеседника."
        )
    public_name = names.get(target, "")
    if target in NAMES and not public_name:
        digest = hashlib.sha256((campaign.get("world_id", "") + target).encode()).digest()
        public_name = NAMES[target][int.from_bytes(digest[:4], "big") % len(NAMES[target])]
    if target and target not in NAMES:
        public_name = next(a["name"] for a in actors if a["id"] == target)
    return {
        "mode": "description" if world_question else "dialogue" if social and target else "scene",
        "target_id": "" if world_question else target or "",
        "topics": topics,
        "tasks": [] if world_question else [TASKS[key] for key in topics],
        "speech_act": act,
        "approach_requested": approach,
        "public_name": public_name if "name" in topics else "",
        "name_established": target in names or target not in NAMES,
        "clarification": clarification,
        "actors": aliases,
    }
