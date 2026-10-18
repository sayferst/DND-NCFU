"""Contextual semantic evidence with a conservative compatibility path."""

import re

from rpg_vkr.commands import CHAT_TARGETS
from rpg_vkr.domain.meaning import Meaning
from rpg_vkr.narrative.speech import explicit_target, speech_details, unquoted


def addressed_to_master(text):
    return bool(re.match(r"\s*(?:мастер|рассказчик|ведущий)\b", unquoted(text)))


def infer_meaning(session, text, interpretation=None):
    from rpg_vkr.narrative.dialogue import last_interlocutor

    act, topic = speech_details(text)
    target = explicit_target(text)
    visible_question = topic == "appearance" and not re.search(
        r"\b(?:вы|ты|ваш\w*|твой\w*)\b", unquoted(text)
    )
    if addressed_to_master(text) or visible_question:
        if target is None and re.search(r"\b(?:он|она|его|ее|ней|нем)\b", unquoted(text)):
            target = last_interlocutor(session)
        return Meaning("master", target or "", "question", topic)
    if topic == "local_help" and ("?" in text or "нужна помощь" in unquoted(text)):
        target = target or last_interlocutor(session)
        if target:
            return Meaning("dialogue", target, "question", "local_help")
    if interpretation and interpretation.kind in {"master", "dialogue"}:
        target = interpretation.target or target
        if interpretation.speech_act:
            act, topic = interpretation.speech_act, interpretation.topic
        # Explicit known refusal/farewell and contact cues beat a generic model topic.
        cue_act, cue_topic = speech_details(text)
        if cue_act != "question" or cue_topic in {"local_help", "appearance"}:
            act, topic = cue_act, cue_topic
        if interpretation.kind == "master":
            return Meaning("master", target or "", act, topic)
        if target:
            return Meaning("dialogue", target, act, topic)
    if act in {"refusal", "insult", "threat", "apology", "farewell"}:
        target = target or last_interlocutor(session)
        if target:
            return Meaning("dialogue", target, act, topic)
    return None


def meaning_command(meaning):
    if meaning.kind == "master":
        return "спросить мастера"
    return next(key for key, value in CHAT_TARGETS.items() if value == meaning.target)
