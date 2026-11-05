"""Offline language adapter for universal attempt primitives and real physical IDs.

This module interprets words only. It never assigns DC, consequences, rewards,
material properties, or a successful outcome. A model can propose the same plan.
"""

import re
from dataclasses import dataclass

from rpg_vkr.domain.interactions import nonexecuting
from rpg_vkr.narrative.speech import unquoted

VERSION = 1
STAGES = (
    "INTENT",
    "FACT_CHECK",
    "FEASIBILITY",
    "ATTEMPT_PLAN",
    "CHECK_SELECTION",
    "RESOLUTION",
    "WORLD_COMMIT",
    "NARRATION",
)
MODES = (
    "AUTO_SUCCESS",
    "CHECK_REQUIRED",
    "ATTEMPT_WITHOUT_TARGET_SUCCESS",
    "CLARIFICATION_REQUIRED",
)


@dataclass(frozen=True)
class Intent:
    kind: str
    text: str


def interpret(text):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        return None
    value = unquoted(text).casefold().replace("ё", "е").strip()
    roots = (
        r"(?:разбир|дела|собир|колд|созда|взлет|лет|подбир|бер|иду|пой|исслед|чин|ремонт|использ)"
    )
    if nonexecuting(text, roots):
        return None
    if re.match(r"(?:расскажи|опиши|объясни|думаю|планирую|хочу узнать)\b", value):
        return None
    if re.search(r";|\b(?:затем|потом)\b|\bи\s+(?:беру|забираю|покуп|прода|иду|атак|колд)", value):
        return Intent("clarify", text)
    patterns = (
        (
            "negotiate_food",
            r"(?:договар|договор|распредел|предлага|поддерж).*(?:продовольств|рацион|припас)",
        ),
        ("restore", r"(?:собир|собра|восстан).*(?:обратно|прежн|исходн)"),
        ("repair", r"(?:чиню|почин|ремонт|латаю|восстан)"),
        ("transform", r"(?:делаю|делать|изгот|сооруж|превращ|собир|собра)"),
        ("magic", r"(?:колд|материализ|призыв|магией созда)"),
        ("use", r"(?:использ|применя|сажусь|подпер|подпир|разрез|укры|привяз|рыбач|ловлю рыбу)"),
        ("take", r"^(?:я\s+)?(?:пытаюсь\s+)?(?:подбира\w*|подобра\w*|беру|взять)\b"),
        ("explore", r"(?:исслед|осматри|осмотр).*(?:дорог|троп|пут[ьи])"),
        (
            "move",
            r"^(?:я\s+)?(?:иду|пойду|отправля\w*|двига\w*|шага\w*|перехо\w*).*(?:дорог|троп|пут[ьи])",
        ),
    )
    for kind, pattern in patterns:
        if re.search(pattern, value):
            return Intent(kind, text)
    return None


def execute(e, args):
    from rpg_vkr.domain.attempt_plans import clarify, infer_plan, resolve

    if (
        not isinstance(args, dict)
        or set(args) != {"text", "version"}
        or type(args["version"]) is not int
        or args["version"] != VERSION
    ):
        raise ValueError("Неизвестная версия свободного действия.")
    intent = interpret(args["text"])
    if intent is None or intent.kind == "clarify":
        clarify("Опишите одну конкретную попытку и её цель.")
    if intent.kind == "negotiate_food":
        from rpg_vkr.domain.food_negotiation import execute as negotiate

        value = intent.text.casefold()
        policy = (
            "guards"
            if re.search(r"поддерж\w*\s+гарнизон", value)
            else ("civilians" if re.search(r"поддерж\w*\s+жител", value) else "balanced")
        )
        return negotiate(e, {"policy": policy})
    return resolve(e, infer_plan(e, intent))
