"""Small dialogue brief from explicit words and public canon, without executing actions."""

import hashlib
import re

from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.world import LOCATIONS
from rpg_vkr.narrative.speech import explicit_target, speech_details

# Original project name lists; independent from the combat RNG and player biography.
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
    "wellbeing": "Прямой ответ NPC, как у него дела сейчас, с учётом его занятия.",
    "help": "Ответ NPC: нужна ли помощь и с чем; предложение не означает согласие героя.",
    "name": "Собеседник представляется указанным именем в прямой речи; имя не менять.",
    "occupation": "NPC отвечает, чем сейчас занят; опирайся на занятие и цель из карточки.",
    "appearance": "Ответ о наблюдаемой внешности без повторения всей сцены.",
    "background": "Ответ о происхождении из публичных фактов NPC.",
    "directions": "Прямой ответ о дороге из доступных фактов.",
    "wares": "Ответ о торговом предложении без совершения сделки за игрока.",
}


def name_forms(name):
    """Limited inflections for our original name lists, without fuzzy substring binding."""
    value = name.casefold()
    if value.endswith("ия"):
        return {value, value[:-2] + "ии", value[:-2] + "ию", value[:-2] + "ией"}
    if value.endswith("а"):
        return {value, *(value[:-1] + end for end in ("ы", "и", "е", "у", "ой"))}
    if value.endswith("й"):
        return {value, *(value[:-1] + end for end in ("я", "ю", "ем", "е"))}
    return {value, *(value + end for end in ("а", "у", "ом", "е"))}


def turn_brief(frame, text, *, campaign=None, memory=None, master=False):
    campaign, memory = campaign or {}, memory or {}
    normal = text.casefold().replace("ё", "е")
    visible = [key for key in NAMES if LOCATIONS[ACTORS[key][1]] == frame.location]
    names = {
        f["subject"]: f["value"]
        for f in memory.get("facts", ())
        if f.get("key") == "public_name" and f.get("subject") in visible
    }
    target = explicit_target(text)
    if target is None:
        mentioned = [
            key
            for key, name in names.items()
            if any(re.search(r"\b" + re.escape(form) + r"\b", normal) for form in name_forms(name))
        ]
        if len(mentioned) == 1:
            target = mentioned[0]
    topics = [key for key, pattern in TOPICS.items() if re.search(pattern, normal)]
    act, topic = speech_details(text)
    if topic in TASKS and topic not in topics and topic != "help":
        topics.append(topic)
    approach = bool(re.search(r"\b(?:подойду|подойти|подхожу)\b", normal))
    social = bool(
        topics
        or re.search(r"спро|спраш|скажи|скажите|поговор", normal)
        or approach
        or act in {"greeting", "farewell", "refusal", "apology", "insult", "threat"}
    )
    if target is None and social:
        previous = campaign.get("interlocutor_id")
        if re.search(r"\b(?:нее|ней|ей|она|девушка|женщина)\b", normal):
            candidates = [key for key in visible if key == "villager"]
        elif re.search(r"\b(?:него|нему|ним|он)\b", normal):
            candidates = [key for key in visible if key != "villager"]
        else:
            candidates = visible
        if previous in candidates:
            target = previous
        elif len(candidates) == 1:
            target = candidates[0]
    if master:
        return {
            "mode": "description",
            "target_id": target if target in visible else "",
            "tasks": [],
        }
    clarification = ""
    if social and target not in visible:
        clarification = (
            "К кому вы хотите подойти или обратиться: к стражнику или к женщине с яблоками?"
            if set(visible) == {"guard", "villager"}
            else "К кому вы обращаетесь? Назовите собеседника рядом с вами."
        )
    public_name = names.get(target, "")
    if target in NAMES and not public_name:
        digest = hashlib.sha256((campaign.get("world_id", "") + target).encode()).digest()
        public_name = NAMES[target][int.from_bytes(digest[:4], "big") % len(NAMES[target])]
    return {
        "mode": "dialogue" if social and target in visible else "scene",
        "target_id": target if target in visible else "",
        "topics": topics,
        "tasks": [TASKS[key] for key in topics],
        "speech_act": act,
        "approach_requested": approach,
        "public_name": public_name if "name" in topics else "",
        "name_established": target in names,
        "clarification": clarification,
    }
