"""Plain-text master protocol: no model-produced game commands or fact transactions."""

import json
import re
from copy import deepcopy

from rpg_vkr.domain.director import Proposal, StoryFact, mechanical_commands
from rpg_vkr.narrative.instructions import load_instructions
from rpg_vkr.narrative.routing import addressed_to_master, simple_action
from rpg_vkr.narrative.speech import speech_details
from rpg_vkr.narrative.story_prompt import STORY_CONTRACT, render_context, writing_profile
from rpg_vkr.narrative.story_quality import check_story_quality, spoken
from rpg_vkr.narrative.turn_brief import turn_brief


def mechanical_request(text):
    from rpg_vkr.commands import normalise_action

    local = simple_action(text)
    if local and local.command in mechanical_commands():
        return local.command
    value = normalise_action(text)
    value = re.sub(r"^(?:я\s+)?(?:хочу\s+|попробую\s+|буду\s+)?", "", value)
    return value if value in mechanical_commands() else None


def master_question(text):
    return addressed_to_master(text) or (
        speech_details(text)[1] == "appearance"
        and not re.search(r"\b(?:ты|вы|ваш\w*|твой\w*)\b", text.casefold())
    )


def story_context(frame, model, text, *, memory=None, campaign=None, history=(), confirmed=False):
    memory = deepcopy(memory or {})
    memory.pop("examples", None)
    # Raw model prose stays in the journal, never in authoritative world facts.
    for event in memory.get("events", ()):
        if event.get("source") != "rules":
            event.pop("result", None)
    facts = frame.to_dict()
    facts["visible_actors"] = [a.split(":", 1)[0] for a in facts["visible_actors"]]
    latest_is_scene = bool(
        history and list(history)[-1].get("source", "").startswith("scene-director-")
    )
    if confirmed and not latest_is_scene:
        facts["confirmed_result"] = facts["confirmed_result"][:1200]
    else:
        facts.pop("confirmed_result", None)
    brief = turn_brief(frame, text, campaign=campaign, memory=memory, master=master_question(text))
    catalog_scene = (campaign or {}).get("catalog_scene", [])
    if confirmed:
        brief = {**brief, "mode": "result", "clarification": ""}
    if brief.get("mode") == "dialogue":
        facts.pop(
            "scene", None
        )  # A conversation needs the speaker's situation, not another panorama.
        memory["npcs"] = [n for n in memory.get("npcs", ()) if n.get("id") == brief["target_id"]]
    recent = []
    for event in list(history)[-3:]:
        entry = {"player_message": event.get("player", event.get("player_message", ""))[:300]}
        if event.get("source") == "rules":
            entry["rules_result"] = event.get("result", event.get("confirmed_result", ""))[:350]
        elif event.get("source") in {"scene-director-5", "scene-director-6"}:
            actor_id = event.get("actor_id", "")
            if actor_id and any(
                (a.get("id") == actor_id) for a in (campaign or {}).get("actors", [])
            ):
                entry["npc_reply"] = spoken(event.get("result", ""))[:350]
                entry["actor_id"] = actor_id
        recent.append(entry)
    context = {
        "obstacle": (campaign or {}).get("obstacle", ""),
        "receipt": (campaign or {}).get("receipt") if confirmed else None,
        "persistent_memory": (campaign or {}).get("persistent_memory", {}),
        "proposed_memories": (campaign or {}).get("proposed_memories", []),
        "player_message": text,
        "current_scene": facts,
        "hero_description": (campaign or {}).get("hero_description", ""),
        "world_brief": (campaign or {}).get("world_brief", ""),
        "catalog_scene": catalog_scene,
        "objects": (campaign or {}).get("objects", []),
        "actor_attempt_result": (campaign or {}).get("actor_attempt_result", "")
        if confirmed
        else "",
        "death_confirmed": (campaign or {}).get("death_confirmed", False) if confirmed else False,
        "challenge_result": (campaign or {}).get("challenge_result", "") if confirmed else "",
        "interaction_result": (campaign or {}).get("interaction_result", "") if confirmed else "",
        "resolution": (campaign or {}).get("resolution", []) if confirmed else [],
        "known_observations": (campaign or {}).get("known_observations", []),
        "memory": memory,
        "recent_events": recent,
        "turn_brief": brief,
        "writing_profile": writing_profile(model, text),
        "task": "Опиши уже подтверждённый итог без повторного действия."
        if confirmed
        else (
            "Ответь на последнее сообщение и на все перечисленные вопросы. "
            "Не копируй прошлый ответ."
        ),
    }
    if master_question(text):
        context["task"] += " Это вопрос ведущему о наблюдаемом: ответь описанием, не от лица NPC."
    return context


def story_payload(
    frame, model, text, *, memory=None, campaign=None, history=(), confirmed=False, context=None
):
    context = context or story_context(
        frame, model, text, memory=memory, campaign=campaign, history=history, confirmed=confirmed
    )
    return {
        "model": model,
        "stream": False,
        **({"think": False} if model.casefold().startswith("qwen3") else {}),
        "keep_alive": "5m",
        "options": {
            "num_ctx": 8192 if len(context["hero_description"]) > 1500 else 4096,
            "num_predict": context["writing_profile"]["num_predict"],
            "temperature": 0.45,
            "repeat_penalty": 1.0,
            "repeat_last_n": 128,
            "num_gpu": 0,
            "num_thread": 4,
        },
        "messages": [
            {"role": "system", "content": load_instructions() + "\n\n" + STORY_CONTRACT},
            {
                "role": "user",
                "content": render_context(context)
                + ("\n/no_think" if model.casefold().startswith("qwen3") else ""),
            },
        ],
    }


def story_text(data, *, confirmed=False):
    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise ValueError("В ответе нет сообщения модели")
    if data.get("done_reason") == "length" or data.get("done") is False:
        raise ValueError("Рассказ обрезан лимитом генерации")
    message = data["message"]
    if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
        raise ValueError("В ответе нет текста рассказчика")
    text = message["content"].strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|text)?\s*|\s*```$", "", text).strip()
    if text.startswith("{"):
        # Compatibility only: never execute a command or apply facts mined from a prose reply.
        value = json.loads(text)
        if not isinstance(value, dict) or value.get("mechanical_command"):
            raise ValueError("Рассказчик вернул игровую команду вместо рассказа")
        if set(value) not in (
            {"narration"},
            {"mechanical_command", "focus_id", "narration", "facts"},
        ):
            raise ValueError("Модель вернула служебные поля вместо рассказа")
        text = value.get("narration")
    if isinstance(text, str):
        text = re.sub(r"^\s*(?:Мастер|Рассказчик|ИИ)\s*:\s*", "", text, flags=re.I)
        text = re.sub(r'[“"]([^”"\n]+)[”"]', r"«\1»", text)

        def speaker_line(match):
            speech = match[2].strip()
            if not speech.startswith("«"):
                speech = "«" + speech + "»"
            return match[1] + " отвечает: " + speech

        text = re.sub(r"(?m)^(Стражник|Жительница|Торговец):\s*([^\n]+)$", speaker_line, text)
    validate_story_text(text, confirmed=confirmed)
    return text.strip()


def validate_story_text(text, *, confirmed=False, legacy=False):
    if legacy:
        return legacy_story_text(text, confirmed=confirmed)
    from rpg_vkr.narrative.limits import MAX_PROSE
    from rpg_vkr.narrative.story_quality import prose_only, unsupported_numeric_claim

    if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROSE:
        raise ValueError("Пустой или слишком большой текст рассказа.")
    if any(ord(c) < 32 and c not in "\n\t" for c in text) or re.search(r"<[^>]+>", text):
        raise ValueError("В ответе недопустимая разметка или управляющие символы.")
    if re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        raise ValueError("В ответе посторонний язык; нужен русский текст.")
    if not re.search(r"[А-Яа-яЁё]", text):
        raise ValueError("В ответе нет русского текста.")
    if not confirmed and unsupported_numeric_claim(prose_only(text)):
        raise ValueError("Рассказчик назначил неподтверждённый механический результат.")


def legacy_story_text(text, *, confirmed=False):
    if not isinstance(text, str) or not 20 <= len(text.strip()) <= 1500:
        raise ValueError("Нужен законченный рассказ от 20 до 1500 символов")
    if re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]|<|>", text):
        raise ValueError("В рассказ попали посторонний язык или разметка")
    letters = re.findall(r"[^\W\d_]", text)
    russian = re.findall(r"[А-Яа-яЁё]", text)
    if len(russian) < 12 or len(russian) / max(1, len(letters)) < 0.7:
        raise ValueError("Рассказ должен быть написан по-русски")
    prose = re.sub(r"«[^»]*»|(?:^|\n)\s*—[^\n]*", "", text)
    if not confirmed and re.search(
        r"\bвы\s+(?:получили|получаете|продали|продаете|купили|покупаете|"
        r"нанесли|наносите|потеряли|потеряете|потратили|забрали|забираете|"
        r"бер[её]те|взяли|выбрасываете|выбросили|перекладываете|переложили|"
        r"переда[её]те|передали|убегаете|убежали|уходите|ушли|перемещаетесь)\b",
        prose,
        re.I,
    ):
        raise ValueError("Рассказчик назначил неподтверждённый механический результат")


def story_proposal(data, frame, player_text, *, context=None, previous=()):
    text = story_text(data)
    context = context or {}
    master = master_question(player_text)
    brief = context.get("turn_brief") or turn_brief(frame, player_text, master=master)
    check_story_quality(
        text,
        frame,
        player_text,
        brief=brief,
        previous=previous,
        campaign=context,
    )
    target = "" if master else brief.get("target_id", "")
    if not target and not master:
        from rpg_vkr.narrative.turn_brief import mentioned_actors

        candidates = mentioned_actors(text, brief.get("actors", []))
        if len(candidates) == 1 and spoken(text):
            target = candidates[0]
    if not spoken(text):
        target = ""
    facts = ()
    if (
        target in {"guard", "villager", "merchant"}
        and "name" in brief.get("topics", ())
        and not brief.get("name_established")
        and brief["public_name"].casefold() in text.casefold()
    ):
        facts = (StoryFact(target, "public_name", brief["public_name"]),)
    return Proposal("", target, text, facts)


def repair_payload(payload, reason):
    result = deepcopy(payload)
    result["messages"][0]["content"] += (
        " Первая попытка отклонена: "
        + str(reason)[:900]
        + ". Ответь обычным законченным русским текстом, без игровых команд и JSON."
    )
    result["options"]["num_predict"] = writing_profile(payload["model"])["repair_predict"]
    result["options"]["temperature"] = 0.2
    return result
