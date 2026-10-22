"""Independent diagnostic probes against unchanged e5e8996; no provider calls."""

import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import last_interlocutor
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import story_context
from rpg_vkr.storage.knowledge import retrieve

OUT = Path("/tmp")
MODEL = "deepseek/audit-no-provider"


def new_session(seed=5):
    session = Session.create_hero(
        Character(name="Лея"),
        "scout",
        seed=seed,
        description="Картограф ищет сестру",
        world_brief="Речной город, тайны гильдий",
    )
    value = {
        "title": "Переправа",
        "opening": "Под аркой шумит река. Веста сверяет карту, дозорный осматривает мост.",
        "private_plot": "Пропажа сестры связана с изменением торгового пути.",
        "hooks": ["Узнать о закрытой переправе"],
        "start": "landing",
        "places": [
            {
                "id": "landing",
                "name": "Мост над рекой",
                "parent": "",
                "description": "Каменная арка нависает над рекой.",
            },
            {
                "id": "gallery",
                "name": "Галерея карт",
                "parent": "landing",
                "description": "Пустая галерея ведёт к мосту.",
            },
        ],
        "definitions": [
            {
                "id": "cartographer_type",
                "name": "Веста",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {
                    "hp_max": 8,
                    "goals": ["Сохранить карты"],
                    "appearance": "Седая коса, синий плащ",
                },
            },
            {
                "id": "sentinel_type",
                "name": "Дозорный",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {
                    "hp_max": 10,
                    "goals": ["Охранять мост"],
                    "appearance": "Латный нагрудник",
                },
            },
            {
                "id": "token_type",
                "name": "Медный жетон",
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"mass_g": 5, "volume_ml": 1},
                "price_cp": 10,
            },
        ],
        "entities": [
            {
                "id": "vesta",
                "definition_id": "cartographer_type",
                "parent_id": "landing",
                "state": {"hp": 8},
            },
            {
                "id": "sentinel",
                "definition_id": "sentinel_type",
                "parent_id": "landing",
                "state": {"hp": 10},
            },
            {
                "id": "token",
                "definition_id": "token_type",
                "parent_id": "vesta",
                "owner_id": "vesta",
                "quantity": 1,
            },
        ],
    }
    session.start_world(build_world(value, session, "diagnostic-fixture"))
    return session


def context_for(session, message, confirmed=False, history=()):
    return story_context(
        build_frame(session),
        MODEL,
        message,
        memory=retrieve(session, message),
        campaign=campaign_context(session, last_interlocutor(session)),
        confirmed=confirmed,
        history=history,
    )


def response(text):
    return {"message": {"role": "assistant", "content": text}, "done": True, "done_reason": "stop"}


def prepare(case):
    generated = case["category"] in {
        "new_npc",
        "insult",
        "negotiation",
        "exploration",
        "unknown_place",
        "magic",
        "unexpected_action",
        "repeat",
        "confirmed_attack",
        "failed_check",
    } or case["id"] in {"dead_silence", "npc_action_not_registered"}
    session = (
        new_session(seed=1 if case["category"] == "failed_check" else 5)
        if generated
        else Session(seed=42)
    )
    if case["category"] == "confirmed_attack":
        session.submit_actor_attempt("атакую дозорного", "sentinel", "attack", False, "Удар", MODEL)
    if case["category"] == "failed_check":
        session.submit_interaction("иду в галерею", WorldPlan((Step("move", "gallery"),)))
        session.submit_interaction(
            "иду к мосту и забираю жетон",
            WorldPlan((Step("move", "landing"), Step("take", "token", 1))),
        )
    return session
