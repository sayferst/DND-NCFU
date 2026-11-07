"""Source-preserving DM target extraction and explicit task-specific context projection."""

import re
from collections import Counter

from rpg_vkr.learning.quality import PRIVATE, UNSAFE
from training.gm_mechanics import actor_map, hp_observation

VERSION = "source-dm-curation-3"
OOC = re.compile(
    r"\b(?:critical role|geek\s*(?:&|and)\s*sundry|twitch|subscribe|subscription|"
    r"sponsors?|patreon|kickstarter|merchandise|donations?|commercial break|"
    r"technical difficulties|my name is matt(?:hew)?|thank you for watching|"
    r"see you next week|chat room|buy her a ticket home|next thursday|"
    r"we(?:'ll| will) be right back)\b",
    re.I,
)
EXPLICIT_SEX = re.compile(
    r"\b(?:sexual intercourse|penetrat(?:e|es|ing|ion).{0,30}(?:vagina|anus)|"
    r"(?:lick|suck)(?:s|ing|ed)?.{0,15}(?:penis|clitoris)|(?:rape|raping|raped))\b",
    re.I,
)
UNSUPPORTED_NUMERIC_ADJUDICATION = re.compile(
    r"\b(?:take|takes|took|deal|deals|dealt|regain|regains|gain|gains|lose|loses)\s+"
    r"\d+\s+(?:points? of|hit points?|damage|gold|silver|copper)|\bDC\s*\d+",
    re.I,
)


def publisher_variants(text):
    """Known published regex/Discord transformations only; never fuzzy-match an author."""
    if not isinstance(text, str):
        return set()
    values = {text, re.sub(r"\(.*?\)", "", text)}
    for value in tuple(values):
        value = re.sub(r"<(@[!&]?|#)\d+>", "", value)
        value = re.sub(r"<a?(:\w+?:)\d+>", r"\1", value)
        values.add(value)
    return {value.strip() for value in values if value.strip()}


def text_screen(text, *, grounded):
    if not isinstance(text, str) or not text.strip():
        return "EMPTY_TARGET"
    if len(re.findall(r"\b\w+\b", text)) < 6:
        return "SHORT_TARGET_RETAINED_FOR_REVIEW"
    if any(token in text for token in ("<|im_start|>", "<|im_end|>", "<s>", "</s>")):
        return "CHAT_CONTROL_TOKEN"
    if PRIVATE.search(text) or UNSAFE.search(text):
        return "PRIVACY_OR_INSTRUCTION_REVIEW"
    if OOC.search(text):
        return "OUT_OF_GAME_OR_PERSONA_ADVERTISEMENT"
    if EXPLICIT_SEX.search(text):
        return "EXPLICIT_SEXUAL_CONTENT_REVIEW"
    if not grounded and UNSUPPORTED_NUMERIC_ADJUDICATION.search(text):
        return "NUMERIC_ADJUDICATION_WITHOUT_STRUCTURED_RECEIPT"
    return None


def grounding_screen(text, record):
    """Flag explicit contradictions; absent source detail remains unverified, never zero."""
    if re.search(r"(?m)^\s*(?:DM|GM)\s*[!:].*", text) and re.search(
        r"(?m)^\s*[A-Z][A-Za-z' -]{1,25}!\s*\*", text
    ):
        return "MIXED_DM_AND_PLAYER_ROLE_SEGMENTS"
    life = [
        hp_observation(a.get("hp")) for a in record.get("targets_after", []) if isinstance(a, dict)
    ]
    death = re.search(
        r"\b(?:dies|is dead|falls dead|killed|slain|decapitat\w*|"
        r"finish(?:es|ed)?\s+(?:him|her|it|them)\s+off)\b",
        text,
        re.I,
    )
    if death and life and all(v is not None and v[0] > 0 for v in life):
        if not re.search(
            r"\b(?:not|never|nearly|almost|isn't|wasn't)\b",
            text[max(0, death.start() - 25) : death.start()],
            re.I,
        ):
            return "DEATH_CLAIM_WITH_CONFIRMED_SURVIVING_TARGETS"
    if death:
        # A zero-HP snapshot alone does not prove death, including for player characters.
        return "DEATH_CLAIM_REQUIRES_EXPLICIT_DEATH_EVIDENCE"
    claims = re.findall(r"\b(\d+)\s+(?:points? of\s+)?(?:\w+\s+)?damage\b", text, re.I)
    if claims:
        results = "\n".join(record.get("automation_results", []))
        allowed = set(re.findall(r"\b(\d+)\s+(?:points? of\s+)?(?:\w+\s+)?damage\b", results, re.I))
        if any(n not in allowed for n in claims):
            return "DAMAGE_AMOUNT_NOT_CONFIRMED_IN_AUTOMATION"
    return None


def clean_source_text(text):
    """Presentation normalization only; original utterances remain in source evidence."""
    text = re.sub(r"(?m)^\s*>+\s?", "", text)
    text = text.replace("**", "").replace("*", "").replace("__", "")
    return text.strip()


def source_spans(text, *, max_sentences=5):
    """Contiguous source-only sentence windows; a long sentence is never truncated."""
    boundaries = []
    for match in re.finditer(r"[.!?](?:[\"'”’)]{0,2})(?=\s+|$)", text):
        preceding = text[: match.end()]
        if re.search(r"\b(?:Mr|Mrs|Ms|Dr|St|e\.g|i\.e)\.$", preceding):
            continue
        if re.search(r"\b[A-Z]\.$", preceding):
            continue
        boundaries.append(match.end())
    if not boundaries or boundaries[-1] < len(text):
        boundaries.append(len(text))
    start, sentences = 0, 0
    for end in boundaries:
        sentences += 1
        if sentences >= max_sentences or end == len(text):
            left, right = start, end
            while left < right and text[left].isspace():
                left += 1
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                yield left, right
            start, sentences = end, 0


def linked_dm_targets(record, raw_messages, *, require_non_bot=False, portion="after"):
    """Each published utterance must uniquely match a referenced, prior-state DM message."""
    targets, reasons = [], Counter()
    if portion not in {"before", "after"}:
        raise ValueError("Unknown source utterance portion")
    after = record.get(portion + "_utterances")
    refs = record.get(portion + "_idxs")
    if not isinstance(after, list) or not isinstance(refs, list):
        return [], Counter({"NO_FOLLOWING_UTTERANCES_OR_REFERENCES": 1})
    by_index = {m["index"]: m for m in raw_messages if m.get("status") == "SOURCE_MESSAGE"}
    candidates = [by_index[index] for index in refs if type(index) is int and index in by_index]
    for ordinal, text in enumerate(after):
        matched = [
            m
            for m in candidates
            if isinstance(text, str) and text.strip() in publisher_variants(m.get("content"))
        ]
        if len(matched) != 1:
            reasons[
                "TEXT_SOURCE_AMBIGUOUS" if matched else "TEXT_SOURCE_NOT_EXACTLY_RECONSTRUCTED"
            ] += 1
            continue
        message = matched[0]
        if message.get("author_bot") is True or (
            require_non_bot and message.get("author_bot") is not False
        ):
            reasons["EXPLICIT_NON_BOT_FLAG_REQUIRED_FOR_PRIMARY_CORPUS"] += 1
            continue
        if message.get("role") != "dungeon_master_account":
            reasons["TARGET_ACCOUNT_NOT_TIME_LOCAL_DM"] += 1
            continue
        evidence = message.get("role_evidence")
        if (
            not evidence
            or type(evidence.get("state_index")) is not int
            or evidence["state_index"] >= message["index"]
        ):
            reasons["NO_PRIOR_DM_STATE_EVIDENCE"] += 1
            continue
        if portion == "after":
            state_after = record.get("after_state_idx")
            commands = record.get("command_idxs")
            if (
                type(state_after) is not int
                or state_after >= message["index"]
                or not isinstance(commands, list)
                or not commands
                or any(type(i) is not int or i >= message["index"] for i in commands)
            ):
                reasons["RESULT_OR_COMMAND_NOT_CONFIRMED_BEFORE_TARGET"] += 1
                continue
            embeds = record.get("embed_idxs")
            if isinstance(embeds, list) and any(
                type(i) is int and i >= message["index"] for i in embeds
            ):
                reasons["AUTOMATION_EMBED_NOT_AVAILABLE_BEFORE_TARGET"] += 1
                continue
        reason = text_screen(text, grounded=portion == "after")
        reason = reason or (grounding_screen(text, record) if portion == "after" else None)
        if reason:
            reasons[reason] += 1
            continue
        targets.append({"target": text, "ordinal": ordinal, "message": message})
    return targets, reasons


def compact_actors(record):
    before, after = (
        actor_map(record.get(k)) for k in ("combat_state_before", "combat_state_after")
    )
    fields = ("name", "hp", "effects", "class", "race")
    return {
        "before": [{k: actor[k] for k in fields if k in actor} for actor in before.values()],
        "after": [{k: actor[k] for k in fields if k in actor} for actor in after.values()],
        "projection": "ALL_UNAMBIGUOUS_ACTORS_NAME_HP_EFFECTS_CLASS_RACE_FULL_SOURCE_RETAINED",
    }


def fireball_context(record, ordinal):
    return {
        "task": "narrate_confirmed_outcome",
        "source_language": "en",
        "preceding_utterances": record.get("before_utterances", []),
        "prior_dialogue": record.get("utterance_history", []),
        "actors": compact_actors(record),
        "confirmed_result": {
            k: record[k] for k in ("commands_norm", "automation_results") if k in record
        },
        "earlier_following_utterances": record.get("after_utterances", [])[:ordinal],
    }


def crd3_context(turns, index, *, history_turns=8):
    history = []
    for turn in turns[max(0, index - history_turns) : index]:
        names = turn.get("NAMES")
        text = " ".join(turn.get("UTTERANCES", []))
        history.append(
            {
                "speaker_role": "game_master" if names == ["MATT"] else "player_or_group",
                "source_speakers": names,
                "text": text,
            }
        )
    return {
        "task": "continue_dm_scene",
        "source_language": "en",
        "history": history,
        "mechanics_status": "NO_STRUCTURED_RECEIPT_DO_NOT_TREAT_TEXT_AS_VALIDATED_STATE_MUTATION",
    }


def source_messages(task, context):
    import json

    if task not in {"narrate_confirmed_outcome", "continue_dm_scene"}:
        raise ValueError("Unknown source master task")

    common = (
        "You are the game master of a fantasy tabletop role-playing game. "
        "Respond in English to this English-language scene. Preserve player agency. "
        "Never claim to be a real actor or advertise a show. "
        "The game engine validates mechanical outcomes and persistent changes. "
    )
    instruction = (
        "Narrate the confirmed outcome and respond to the preceding dialogue; "
        "preserve the recorded numbers and do not decide the player's next action."
        if task == "narrate_confirmed_outcome"
        else "Continue the scene as its game master, including NPC speech when appropriate. "
        "There is no structured mechanical receipt; "
        "do not invent confirmed dice or resource changes."
    )
    return [
        {"role": "system", "content": common + instruction},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False, sort_keys=True)},
    ]
