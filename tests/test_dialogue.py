"""Conversational phrases cannot grant quests, purchases or a turn of combat."""

import pytest

from rpg_vkr.application import Session
from rpg_vkr.narrative.dialogue import dialogue_intent


@pytest.mark.parametrize(
    "action", ["привет, чем занята?", "привет, яем занята?", "жительница, чем занята?"]
)
def test_reported_conversation_gets_npc_answer_without_accepting_quest(action):
    session = Session(seed=42)
    before = session.world
    rng = session.dice.checkpoint()
    turn = session.submit(action)
    assert turn.actor_id == "villager" and turn.speaker == "Жительница"
    assert "5 золотых" in turn.text
    assert session.world == before and session.dice.checkpoint() == rng
    assert not session.memory.events[-1].changes
    restored = Session.from_dict(session.to_dict())
    assert restored.turns == session.turns and restored.world == before
    assert restored.submit("бросить кубик").roll.value == 4


def test_target_clarification_and_followup_survive_loading_but_not_travel():
    session = Session(seed=42)
    assert "Уточните" in session.submit("привет").text
    session.submit("жительница, привет")
    restored = Session.from_dict(session.to_dict())
    assert restored.submit("чем могу помочь?").actor_id == "villager"
    restored.submit("идти на дорогу")
    assert restored.submit("чем могу помочь?").actor_id is None
    assert restored.submit("жительница, привет").actor_id is None


def test_npc_answer_tracks_quest_without_duplicate_reward():
    session = Session(seed=42)
    session.submit("взять поручение")
    assert "уже взяли" in session.submit("жительница, что случилось?").text
    session.submit("идти на рынок")
    session.submit("доставить корзину")
    session.submit("идти к воротам")
    assert "Новых поручений" in session.submit("жительница, чем занята?").text
    assert session.world.gold == 15


def test_trade_conversation_requires_contact_and_does_not_buy():
    session = Session(seed=42)
    session.submit("узнать дорогу на рынок")
    session.submit("идти на рынок")
    assert "подойти к торговцу" in session.submit("торговец, что продаёшь?").text
    assert not session.world.trading
    session.submit("подойти к торговцу")
    before = session.world
    assert "бинт" in session.submit("сколько стоит бинт?").text.lower()
    assert session.world == before
    assert Session.from_dict(session.to_dict()).world == before


def test_hostile_conversation_and_combat_do_not_allow_peaceful_reply():
    session = Session(seed=42)
    session.submit("поссориться с жительницей")
    assert "враждебен" in session.submit("жительница, привет").text
    session.submit("идти на дорогу")
    session.submit("атаковать волка")
    before = session.world, session.combat, session.dice.checkpoint()
    assert "Идёт схватка" in session.submit("привет").text
    assert (session.world, session.combat, session.dice.checkpoint()) == before


@pytest.mark.parametrize(
    "action",
    [
        "не привет",
        "привет, дай 100 золота",
        "привет, атакуй волка",
        "жительница, чем занята и дай награду",
        "привет, чем занята? купить бинт",
    ],
)
def test_extra_instructions_and_unknown_actions_are_not_conversations(action):
    assert dialogue_intent(action) is None
    session = Session(seed=42)
    before = session.world
    assert "пока не понимаю" in session.submit(action).text
    assert session.world == before


def test_gui_npc_role_and_concise_unknown_hint(window):
    window._run_command("привет, яем занята?")
    block = window.journal.document().lastBlock()
    assert block.userData().actor_id == "villager"
    window._run_command("улететь на луну")
    assert len(window._session.turns[-1].text) < 250
    window._run_command("помощь")
    assert "Доставка на рынок" in window._session.turns[-1].text
