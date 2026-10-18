"""Conservative conversation cues and explicit addressee checks, never fuzzy actions."""

import re

from rpg_vkr.commands import CHAT_TARGETS, normalise_action

ROOTS = r"стражник\w*|жительниц\w*|женщин\w*|девушк\w*|торгов\w*|куп[ец]\w*"


def unquoted(text):
    return re.sub(r'«[^»]*»|"[^"]*"|“[^”]*”', "", normalise_action(text)).replace("ё", "е")


def _identity(word):
    if word.startswith("стражник"):
        return "guard"
    if word.startswith(("жительниц", "женщин", "девушк")):
        return "villager"
    return "merchant"


def explicit_target(text):
    text = unquoted(text)
    address = re.search(
        rf"(?:\b(?:к|у|со?|с)\s+|\b(?:спрашиваю|спросить|спрошу)\s+)({ROOTS})\b",
        text,
    )
    if address:
        return _identity(address[1])
    address = re.match(rf"\s*({ROOTS})\s*[:,]", text)
    if address:
        return _identity(address[1])
    identities = {_identity(m[0]) for m in re.finditer(rf"\b({ROOTS})\b", text)}
    return next(iter(identities)) if len(identities) == 1 else None


def speech_details(text):
    text = unquoted(text)
    text = re.sub(rf"^\s*(?:{ROOTS})\s*[:,]\s*", "", text)
    if re.search(r"\b(цитирую|он сказал|она сказала|мне сказали|что значит)\b", text):
        return "question", "other"
    if re.search(r"\b(?:не отказываюсь|не хочу отказываться|не извиняюсь)\b", text):
        return "question", "other"
    if re.search(
        r"\b(?:до свидания|прощай\w*|мне пора|хорошего.{0,12}дня|доброго.{0,12}пути|хорошего ня)\b",
        text,
    ):
        return "farewell", "other"
    if re.search(r"\b(извини\w*|простите|прошу прощения|прости)\b", text):
        return "apology", "other"
    if re.search(r"\b(?:я\s+)?(?:тебя|вас)\s+(?:убью|зарежу|ударю)\b", text):
        return "threat", "other"
    if re.search(
        r"^(?:да\s+)?(?:пошел|пошла|пошли|иди|идите)\s+(?:ты\s+)?(?:на\s*)?(?:хер|хуй)\b", text
    ):
        return "insult", "other"
    if re.search(r"\b(?:ты|вы)\s+(?:дура\w*|тупиц\w*|идиот\w*)\b", text):
        return "insult", "other"
    if re.search(r"\b(?:не соглас\w*|не буду|не хочу|отказываюсь)\b", text):
        return "refusal", "help" if re.search(r"корзин|поручен|помо", text) else "other"
    if re.search(r"\b(?:подойду|подойти|подхожу)\b", text):
        return "contact", "greeting"
    if re.search(r"чем.{0,25}(?:занят|занима)|(?:что|чего).{0,30}дела|яем занята", text):
        return "question", "occupation"
    if re.search(r"внешност|выгляд|выгляжу|одет|волос|глаза|цвет глаз", text):
        return "question", "appearance"
    if re.search(r"происхожд|семь|родител|откуда.{0,15}(?:ты|вы)|рас[аы]|народ", text):
        return "question", "background"
    if re.search(
        r"(?:подня|поднят|перевер|собра).{0,30}(?:корзин|яблок)|(?:корзин|яблок).{0,30}(?:подня|собра|перевер)",
        text,
    ):
        return "question", "local_help"
    if re.search(r"помощ|помочь|поручен|работ|что случилось|доставить корзин", text):
        return "question", "help"
    if re.search(r"рын[ок]|рынка|пройти|дорог", text):
        return "question", "directions"
    if re.search(r"ассортимент|товар|прода|бинт|\bцен(?:а|ы|у|ой|е|ник)\b", text):
        return "question", "wares"
    if re.search(r"\b(?:привет|здравствуй\w*)\b", text):
        return "greeting", "greeting"
    return "question", "other"


def command_target(command, location=None):
    from rpg_vkr.domain.combat import ANGER_COMMANDS, ATTACK_COMMANDS, STEALTH_COMMANDS

    if command in {"подойти к стражнику", "подойти к жительнице"}:
        return "guard" if "стражнику" in command else "villager"
    if command == "поговорить" and location:
        return {"gate": "guard", "market": "merchant"}.get(location)
    target = CHAT_TARGETS.get(command) or ATTACK_COMMANDS.get(command)
    target = target or ANGER_COMMANDS.get(command) or STEALTH_COMMANDS.get(command)
    if target:
        return target
    if command in {"подойти к торговцу", "торговля", "купить бинт", "продать бинт"}:
        return "merchant"
    if command in {
        "взять поручение",
        "поговорить с жительницей",
        "помочь жительнице",
        "помочь",
        "помочь собрать яблоки",
    }:
        return "villager"
    if command in {"поговорить со стражником", "узнать дорогу на рынок"}:
        return "guard"
    return None


def validate_binding(text, command, *, location=None, active_target=None, interlocutor=None):
    target, selected = explicit_target(text), command_target(command, location)
    act, _ = speech_details(text)
    if target is None and act in {"refusal", "insult", "threat", "apology", "farewell"}:
        target = interlocutor
    if command == "атаковать":
        selected = active_target
    if target and selected and target != selected:
        return "Уточните намерение: названный собеседник не совпал с выбранной целью."
    speech = act in {"refusal", "insult", "threat", "apology", "farewell"} or bool(
        re.search(r"^(?:я\s+)?(?:спросить|спрашиваю|спрошу|могу ли|можно ли)\b", unquoted(text))
    )
    speech = speech or (act == "question" and "?" in text)
    if act in {"refusal", "insult", "threat", "apology", "farewell"}:
        if command not in CHAT_TARGETS and command != "уточнить намерение":
            return "Реплика требует реакции собеседника. Уточните, к кому обращаетесь."
    if act == "contact" and command not in {
        "подойти к стражнику",
        "подойти к жительнице",
        "подойти к торговцу",
        *CHAT_TARGETS,
    }:
        return "Вы обозначили подход к собеседнику; другое действие не выполнено."
    harmless = {
        "осмотреться",
        "инвентарь",
        "состояние",
        "задание",
        "помощь",
        "уточнить намерение",
        "спросить мастера",
    }
    if speech and command not in CHAT_TARGETS and command not in harmless:
        return "Реплика требует ответа или уточнения; действие за вас не выполнено."
    return None
