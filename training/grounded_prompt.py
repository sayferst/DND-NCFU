"""Lossless relevant-fact projection for narrator prompts; full audit states stay in rows."""

import json
from copy import deepcopy

SYSTEM = (
    "Ты ведёшь взрослое фэнтезийное приключение по-русски. "
    "Опиши только подтверждённый результат и его последствия. "
    "Сохраняй один стиль: обычно1–2 предложения, для значимого исхода3–5. "
    "Не решай следующий ход за игрока, не добавляй предметы, способности и ресурсы. "
    "Жестокость допустима по фактам сцены; откровенную эротику не включай."
)


def messages(row):
    state = row["public_context"]["state"]
    op = row["engine_receipt"]["operation"]
    hero = state["hero"]
    obj = state["objects"]["subject"]
    context = {
        "place": hero["place"],
        "hero": {k: hero[k] for k in ("mp", "st", "gold", "arrows", "xp", "level")},
        "life": {k: hero["life"][k] for k in ("hp", "maximum", "exhaustion", "dead", "stable")},
        "subject": {
            k: deepcopy(obj[k])
            for k in (
                "id",
                "name",
                "kind",
                "quantity",
                "holder",
                "legal_owner",
                "accessible",
                "durability",
                "properties",
            )
        },
        "weather": state["world"]["weather"],
    }
    if row["engine_receipt"]["roll"]:
        context["abilities"] = hero["abilities"]
    if op in ("craft", "shape", "coat", "join", "repair", "restore", "separate", "deploy"):
        context["tool"] = {
            k: deepcopy(state["objects"]["tool"][k])
            for k in ("id", "name", "holder", "durability", "capabilities")
        }
        context["material"] = {
            k: state["objects"]["material"][k] for k in ("id", "quantity", "accessible")
        }
    if op in (
        "negotiate",
        "service",
        "allocate",
        "supply",
        "barter",
        "trade",
        "sell",
        "refund",
        "inform",
    ):
        context["npc"] = state["npc"]
    if op in ("cast", "heal", "illusion", "sustain", "overcast", "dismiss", "dead_heal", "scroll"):
        context["known_effects"] = hero["known_effects"]
    if op in ("move", "movement", "wait"):
        context["route"] = state["route"]
    if op in ("attack", "heal", "heal_item", "dead_heal", "stabilize", "disarm"):
        context["target_life"] = state["target_life"]
    for key in (
        "overcast_payment_choice",
        "effect_registry",
        "declared_evidence",
        "declared_limits",
        "transfer_destination",
        "transfer_title",
        "two_similar_targets",
        "selected_target",
        "supported_effect_active",
        "prior_material_spent",
        "level_up_confirmed",
        "allowed_talents",
    ):
        value = state["facts"].get(key)
        if value not in (None, {}, [], False):
            context[key] = value
    extras = {
        id: deepcopy(value)
        for id, value in state["objects"].items()
        if id not in ("subject", "tool", "material")
    }
    if extras:
        context["other_objects"] = extras
    receipt = {
        k: deepcopy(v)
        for k, v in row["engine_receipt"].items()
        if k not in ("before_sha256", "after_sha256", "provenance", "limitations")
    }
    # The reference hashes and full source annotation are for audit, not model input.
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {"context": context, "player": row["player_message"], "receipt": receipt},
                ensure_ascii=False,
            ),
        },
    ]
