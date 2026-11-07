"""Bounded Russian surface audit, with explicit coverage limits (not a grammar oracle)."""

import re
from collections import Counter

BAD_PATTERNS = {
    "first_person_third_person": r"\bя\s+(предпочитает|считает|бережёт|ценит|думает)\b",
    "agreement_concern": r"(Меня беспокоит|Нас ещё ждёт)\s+(утраченные записи|запасы|сигналы)",
    "broken_literal": r"\{(?:scene|result|p|npc)[\[\]]",
    "repeated_token": r"\b([а-яё]{3,})\s+\1\b",
    "player_decision": r"\bты\s+(решаешь|соглашаешься|обещаешь|принимаешь решение)\b",
    "unsupported_engine9_execution": r"(исходная SQLite|Engine9)\s+(подтвердила|вычислил)",
}


def audit_texts(texts):
    hits, examples = Counter(), {}
    total = weather = negative = 0
    for uid, text in texts:
        total += 1
        weather += int(bool(re.search(r"\b(дождь|снег|ветер|туман)\b", text.casefold())))
        negative += int(
            bool(re.search(r"\b(нельзя|неизвестн\w*|не подтвержд\w*)\b", text.casefold()))
        )
        for name, pattern in BAD_PATTERNS.items():
            if re.search(pattern, text, re.I):
                hits[name] += 1
                examples.setdefault(name, uid)
    return {
        "checked": total,
        "bounded_pattern_hits": dict(hits),
        "examples": examples,
        "weather_mentions": weather,
        "negative_or_unknown_mentions": negative,
        "scope": (
            "surface patterns only; zero hits does not prove naturalness "
            "or full semantic correctness"
        ),
        "human_reviewed": 0,
    }
