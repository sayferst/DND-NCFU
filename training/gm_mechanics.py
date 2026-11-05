"""Evidence-based curriculum coverage; repertoire words never count as executed mechanics."""

import re
import shlex
from collections import Counter

MECHANICS = {
    "combat_attack": "Атака и попадание/промах",
    "combat_defense": "Защита и реакции",
    "spell_casting": "Применение магии",
    "resource_cost": "Расход ресурсов",
    "damage": "Повреждения",
    "healing": "Лечение",
    "temporary_hp": "Временные HP",
    "zero_hp": "Состояние при нуле HP",
    "death_stabilization": "Смерть, спасброски и стабилизация",
    "conditions_effects": "Состояния и эффекты",
    "d20_checks": "Проверки D20 и сложность",
    "critical_boundaries": "Натуральные 1/20 в допустимых пределах",
    "partial_success": "Частичный успех",
    "crafting": "Создание и переделка вещей",
    "repair": "Ремонт",
    "unconventional_item_use": "Нестандартное использование предметов",
    "physical_capability_limits": "Физические ограничения и доступные способности",
    "movement_travel": "Перемещение и путешествие",
    "exploration": "Исследование и наблюдение",
    "rest_exhaustion": "Отдых и истощение",
    "overcasting": "Перерасход магии по правилам владельца",
    "npc_dialogue": "Диалоги с NPC",
    "persuasion_negotiation": "Убеждение и переговоры",
    "npc_interests_conflict": "Разные интересы участников конфликта",
    "trade_economy": "Торговля и конечные ресурсы",
    "world_consequences": "Последствия для мира",
    "world_memory": "Память о событиях",
    "scene_quest_generation": "Повествовательные сцены и задания",
    "narration": "Повествование",
    "clarification": "Уточнение неизвестных условий",
    "role_contract": "Роль мастера и свобода игрока",
}

PROSE = {
    "crafting": (
        r"\b(?:crafting|crafted|forging|forged|assembling|assembled|tinkering)\b|"
        r"\b(?:craft|carve|forge|assemble|fashion|tinker)(?:s)?\s+"
        r"(?:a|an|the|this|that|your|my|our|his|her|its|their|with)\b|"
        r"изготов|смастер|собира[юе]|выков"
    ),
    "repair": r"\b(?:repair|mend|fixing|repaired)\w*\b|ремонт|почин|чиню",
    "unconventional_item_use": r"\bimprovis\w*\b|использ\w*.+(?:вместо|как)|передел",
    "movement_travel": (
        r"\b(?:travel|journey|walk|climb|swim|fly|flying|teleport)\w*\b|иду|двига|дорог|перемещ"
    ),
    "exploration": r"\b(?:investigat|search|perception|explor|inspect)\w*\b|осмотр|исслед|наблюд",
    "rest_exhaustion": (
        r"\b(?:short rest|long rest|rested|resting|exhaustion|exhausted|campfire|sleep\w*)\b|"
        r"\brest\s+(?:for|here|until|a while|at|in)\b|отдых|истощен|привал"
    ),
    "persuasion_negotiation": (
        r"\b(?:persuad|bargain|negotia|intimidat|deceiv)\w*\b|убежд|переговор|уговор|запуг"
    ),
    "npc_interests_conflict": (
        r"\b(?:refus|demand|alliance|betray|loyalt|interests)\w*\b|"
        r"отказ|интерес|требова|союз|предат"
    ),
    "trade_economy": (
        r"\b(?:merchant|buy|bought|sell|sold|price|gold pieces)\b|"
        r"(?<!find )(?<!finds )\bpurchas(?:e|es|ed|ing)\b|"
        r"купить|покуп|прода|торг|цен[ауе]"
    ),
    "scene_quest_generation": (
        r"\b(?:quest|mission|bounty|rescue|reward|dungeon|ruins)\w*\b|"
        r"задани|поручен|награда|руины"
    ),
    "world_memory": (
        r"\b(?:remember|previously|last time|earlier|already met)\b|помни|раньше|прежде|ранее"
    ),
    "clarification": (
        r"\b(?:what do you|which one|do you mean|clarify)\b|уточн|какой именно|кого именно"
    ),
}

OPERATIONS = {
    "attack": ("combat_attack", "damage"),
    "defend": ("combat_defense",),
    "disarm": ("combat_attack",),
    "cast": ("spell_casting", "resource_cost"),
    "overcast": ("overcasting", "resource_cost", "spell_casting"),
    "heal": ("healing", "resource_cost"),
    "heal_item": ("healing", "resource_cost"),
    "dead_heal": ("healing", "death_stabilization", "physical_capability_limits"),
    "stabilize": ("death_stabilization",),
    "craft": ("crafting", "unconventional_item_use"),
    "shape": ("crafting",),
    "coat": ("crafting",),
    "join": ("crafting",),
    "repair": ("repair",),
    "restore": ("repair",),
    "separate": ("crafting",),
    "deploy": ("unconventional_item_use",),
    "test": ("unconventional_item_use",),
    "capability": ("physical_capability_limits",),
    "illusion": ("spell_casting", "physical_capability_limits"),
    "move": ("movement_travel",),
    "movement": ("movement_travel",),
    "observe": ("exploration",),
    "verify": ("exploration",),
    "compare": ("exploration",),
    "negotiate": ("persuasion_negotiation", "npc_dialogue", "npc_interests_conflict"),
    "allocate": ("npc_interests_conflict", "trade_economy"),
    "inform": ("npc_dialogue",),
    "service": ("npc_dialogue", "trade_economy"),
    "trade": ("trade_economy",),
    "sell": ("trade_economy",),
    "barter": ("trade_economy",),
    "supply": ("trade_economy",),
    "refund": ("trade_economy",),
    "record": ("world_memory",),
    "long_rest": ("rest_exhaustion",),
    "rest": ("rest_exhaustion",),
}


def prose_evidence(text):
    return {
        key: "NARRATIVE_MENTION_NOT_VERIFIED_MECHANIC"
        for key, pattern in PROSE.items()
        if re.search(pattern, text, re.I)
    }


def command_verbs(commands):
    result = []
    for command in commands:
        if not isinstance(command, str):
            continue
        try:
            words = shlex.split(command)
        except ValueError:
            words = command.split()
        if not words:
            continue
        words = [w.casefold() for w in words]
        verb = words[0].lstrip("!")
        if verb in {"i", "init"} and len(words) > 1:
            verb = words[1]
        result.append(verb)
    return result


def hp_observation(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"<(\d+)/(\d+) HP(?:;[^<>]*)?>", value)
    if not match:
        return None
    current, maximum = map(int, match.groups())
    return (current, maximum) if 0 <= current <= maximum and maximum > 0 else None


def actor_map(values):
    if not isinstance(values, list):
        return {}
    names = [v.get("name") for v in values if isinstance(v, dict)]
    if (
        len(names) != len(values)
        or any(not isinstance(n, str) for n in names)
        or len(set(names)) != len(names)
    ):
        return {}
    return {v["name"]: v for v in values}


def fireball_evidence(record):
    """Ignore character-sheet repertoire/description when counting executed mechanics."""
    text = "\n".join(
        x
        for field in ("before_utterances", "after_utterances")
        for x in record.get(field, [])
        if isinstance(x, str)
    )
    tags = prose_evidence(text)
    verbs = set(command_verbs(record.get("commands_norm", [])))
    for verb, key in (
        ("a", "combat_attack"),
        ("attack", "combat_attack"),
        ("cast", "spell_casting"),
        ("save", "d20_checks"),
        ("check", "d20_checks"),
        ("c", "d20_checks"),
        ("roll", "d20_checks"),
        ("r", "d20_checks"),
    ):
        if verb in verbs:
            tags[key] = "RECORDED_COMMAND_NOT_RULE_OR_SUCCESS_PROOF"
    results = "\n".join(x for x in record.get("automation_results", []) if isinstance(x, str))
    if re.search(r"\b(?:rolled a .+ save|saving throw|rolled a .+ check)\b", results, re.I):
        tags["d20_checks"] = "RECORDED_AUTOMATION_RESULT"
    if re.search(r"\b(?:gained|lost|removed)\s+.+", results, re.I):
        tags["conditions_effects"] = "RECORDED_AUTOMATION_RESULT"
    if re.search(r"\b(?:temporary hit points|temporary hp|temp hp)\b", results, re.I):
        tags["temporary_hp"] = "RECORDED_AUTOMATION_RESULT"
    if re.search(
        r"\b(?:spell slot|slots remaining|expended|charges? remaining|ki points?)\b", results, re.I
    ):
        tags["resource_cost"] = "RECORDED_AUTOMATION_RESULT"
    if re.search(r"\b(?:death sav|stabili[sz])\w*\b", results, re.I):
        tags["death_stabilization"] = "RECORDED_AUTOMATION_RESULT"
    before, after = (
        actor_map(record.get(k)) for k in ("combat_state_before", "combat_state_after")
    )
    for name in before.keys() & after.keys():
        old, new = hp_observation(before[name].get("hp")), hp_observation(after[name].get("hp"))
        if old is not None and new is not None and old[1] == new[1]:
            if old[0] != new[0]:
                tags["healing" if new[0] > old[0] else "damage"] = "OBSERVED_NUMERIC_STATE_DELTA"
                tags["world_consequences"] = "OBSERVED_NUMERIC_STATE_DELTA"
            if new[0] == 0:
                tags["zero_hp"] = "OBSERVED_ZERO_HP_NOT_PROOF_OF_DEATH"
        if (
            isinstance(before[name].get("effects"), str)
            and isinstance(after[name].get("effects"), str)
            and before[name]["effects"] != after[name]["effects"]
        ):
            tags["conditions_effects"] = "OBSERVED_EFFECT_FIELD_CHANGE_NOT_UNIVERSAL_RULE"
    if record.get("after_utterances"):
        tags["narration"] = "SOURCE_LINKED_UTTERANCE_ROLE_CHECK_REQUIRED"
    return tags


def reference_evidence(row):
    tags = {
        key: "EXECUTED_SYNTHETIC_REFERENCE" for key in OPERATIONS.get(row["spec"]["operation"], ())
    }
    tags.update(
        {
            "narration": "EXECUTED_SYNTHETIC_REFERENCE",
            "role_contract": "EXPLICIT_PROJECT_INSTRUCTION",
        }
    )
    receipt = row["engine_receipt"]
    if receipt.get("d20_required"):
        tags["d20_checks"] = "EXECUTED_SYNTHETIC_REFERENCE"
    if receipt.get("outcome") == "partial_success":
        tags["partial_success"] = "EXECUTED_SYNTHETIC_REFERENCE"
    if receipt.get("outcome") == "clarification_required":
        tags["clarification"] = "EXECUTED_SYNTHETIC_REFERENCE"
    if receipt.get("changes"):
        tags["world_consequences"] = "EXECUTED_SYNTHETIC_REFERENCE"
    kind = row["spec"].get("goal") if row["spec"]["operation"] == "boundary" else None
    if kind:
        if kind.startswith("overcast") or kind == "payment_choice_missing":
            tags.update(
                {
                    k: "EXECUTED_SYNTHETIC_REFERENCE"
                    for k in ("overcasting", "resource_cost", "spell_casting")
                }
            )
        if kind.startswith(("death", "massive", "nonlethal", "heal_", "stabili")):
            tags["death_stabilization"] = "EXECUTED_SYNTHETIC_REFERENCE"
        if kind.startswith("heal_"):
            tags["healing"] = "EXECUTED_SYNTHETIC_REFERENCE"
        if kind in {"natural_one", "natural_twenty"}:
            tags["critical_boundaries"] = "EXECUTED_SYNTHETIC_REFERENCE"
        if kind in {"exhaustion_six", "long_rest", "short_rest"}:
            tags["rest_exhaustion"] = "EXECUTED_SYNTHETIC_REFERENCE"
        if kind in {"unsupported_flight", "unknown_magic"}:
            tags["physical_capability_limits"] = "EXECUTED_SYNTHETIC_REFERENCE"
        if kind.startswith("agreement_"):
            tags.update(
                {
                    k: "EXECUTED_SYNTHETIC_REFERENCE"
                    for k in ("persuasion_negotiation", "npc_dialogue", "npc_interests_conflict")
                }
            )
    return tags


def counts_by_evidence(rows):
    counts = {key: Counter() for key in MECHANICS}
    for tags in rows:
        for key, evidence in tags.items():
            counts[key][evidence] += 1
    return {key: dict(value) for key, value in counts.items()}
