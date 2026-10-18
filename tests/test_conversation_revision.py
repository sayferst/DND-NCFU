"""Player-reported conversation regressions, persisted reactions and presentation."""

import json
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.social import grievance
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import activity, dialogue_context
from rpg_vkr.narrative.ollama import parse_narration
from rpg_vkr.narrative.records import Narration
from rpg_vkr.narrative.speech import explicit_target
from rpg_vkr.storage.slots import SaveSlots


def talk(session, message, target="villager"):
    command = {
        "villager": "беседа с жительницей",
        "guard": "беседа со стражником",
        "merchant": "беседа с торговцем",
    }[target]
    return session.submit(message, intent=command)


def test_occupation_help_refusal_and_question_are_distinct_without_accepting_quest():
    session = Session(seed=42)
    before = session.world, session.dice.checkpoint()
    occupation = talk(session, "спросить у жительницы, что она делает тут")
    assert "Яблоки собираю" in occupation.text
    assert "5 золотых" not in occupation.text
    assert occupation.dialogue.topic == "occupation"
    help_turn = talk(session, "Спрашиваю жительницу, нужна ли ей помощь.")
    assert "5 золотых" in help_turn.text and "Возьмётесь?" in help_turn.text
    declined = talk(session, "Жительница, я не согласен брать корзину")
    assert "другого помощника" in declined.text
    assert declined.dialogue.act == "refusal"
    assert (session.world, session.dice.checkpoint()) == before
    assert session.world.quest == "available" and session.world.basket == 0


@pytest.mark.parametrize(
    "message,target",
    [
        ("подойду к стражнику", "guard"),
        ("Спрашиваю у жительницы, что она делает", "villager"),
        ("Торговец, можно узнать цену?", "merchant"),
        ("Спрашиваю стражника о жительнице", "guard"),
    ],
)
def test_explicit_addressee_is_stable(message, target):
    assert explicit_target(message) == target


def test_wrong_model_target_cannot_talk_to_different_npc_or_change_state():
    session = Session(seed=42)
    before = session.world, session.combat, session.dice.checkpoint()
    wrong = talk(session, "подойду к стражнику", "villager")
    assert wrong.intent == "уточнить намерение" and wrong.actor_id is None
    assert wrong.dialogue is None and "не совпал" in wrong.text
    assert (session.world, session.combat, session.dice.checkpoint()) == before
    correct = session.submit("подойду к стражнику", intent="подойти к стражнику")
    assert correct.actor_id == "guard" and correct.dialogue.act == "contact"
    assert "Стражник" in correct.text and "корзин" not in correct.text
    observed_instead = session.submit("подойду к стражнику", intent="осмотреться")
    assert observed_instead.intent == "уточнить намерение"


def test_generic_old_commands_cannot_bypass_addressee_or_recent_interlocutor():
    session = Session(seed=42)
    turn = session.submit("Спрашиваю жительницу, что она делает", intent="поговорить")
    assert turn.intent == "уточнить намерение" and turn.actor_id is None
    turn = session.submit("Помогу стражнику", intent="помочь")
    assert turn.intent == "уточнить намерение" and turn.actor_id is None
    talk(session, "Стражник, здравствуй", "guard")
    turn = talk(session, "пошел нахер", "villager")
    assert turn.intent == "уточнить намерение" and turn.actor_id is None
    assert grievance(session.turns, "villager") == 0


def test_insults_end_conversation_apology_reopens_and_do_not_start_combat(tmp_path):
    session = Session(seed=42)
    talk(session, "Жительница, здравствуйте")
    before = session.world, session.combat, session.dice.checkpoint()
    insult = talk(session, "пошел нахер")
    assert insult.dialogue.act == "insult"
    assert "уважительно" in insult.text and "5 золотых" not in insult.text
    talk(session, "пошла нахер")
    assert grievance(session.turns, "villager") == 2
    assert "не хочу продолжать" in session.turns[-1].text
    blocked = session.submit("взять поручение")
    assert "недоступны" in blocked.text and session.world.quest == "available"
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    restored = slots.load(1)
    assert grievance(restored.turns, "villager") == 2
    apology = talk(restored, "Извини, я погорячился")
    assert apology.dialogue.act == "apology" and "не повторится" in apology.text
    assert grievance(restored.turns, "villager") == 1
    assert "5 золотых" in talk(restored, "Нужна ли помощь?").text
    assert (restored.world, restored.combat, restored.dice.checkpoint()) == before
    assert Session.from_dict(restored.to_dict()).to_dict() == restored.to_dict()


@pytest.mark.parametrize(
    "message",
    [
        "Он сказал мне «пошел нахер». Что это значит?",
        "Что значит пошел нахер?",
        "Я не отказываюсь",
        "Я не хочу отказываться от поручения",
    ],
)
def test_quoted_or_negated_speech_cannot_create_a_new_insult_or_refusal(message):
    session = Session(seed=42)
    turn = talk(session, message)
    assert turn.dialogue.act == "question"
    assert grievance(session.turns, "villager") == 0
    assert session.world.quest == "available"


@pytest.mark.parametrize(
    "message,command",
    [
        ("Жительница, я не согласен брать корзину", "взять поручение"),
        ("Спрашиваю торговца, могу ли я купить бинт?", "купить бинт"),
        ("Я тебя убью", "атаковать жительницу"),
        ("пошел нахер", "осмотреться"),
    ],
)
def test_model_cannot_convert_speech_to_purchase_acceptance_or_attack(message, command):
    session = Session(seed=42)
    before = session.world, session.combat, session.dice.checkpoint()
    turn = session.submit(message, intent=command)
    assert turn.intent == "уточнить намерение"
    assert turn.combat is None and turn.dialogue is None
    assert (session.world, session.combat, session.dice.checkpoint()) == before


def test_activity_follows_real_apple_help_and_quest_events():
    session = Session(seed=42)
    assert "рассыпавшиеся" in activity(session, "villager")
    session.submit("помочь собрать яблоки")
    assert "собрала" in activity(session, "villager")
    assert "Яблоки уже собраны" in talk(session, "чем занята?").text
    session.submit("взять поручение")
    assert "ждёт доставки" in activity(session, "villager")


def test_social_history_rejects_tampering_and_is_atomic_on_other_validation_failure(monkeypatch):
    session = Session(seed=42)
    talk(session, "пошел нахер")
    data = session.to_dict()
    data["turns"][0]["dialogue"]["after"] = 3
    with pytest.raises(ValueError):
        Session.from_dict(data)
    before = session.to_dict()
    from rpg_vkr.domain.memory import WorldMemory

    monkeypatch.setattr(
        WorldMemory, "append", lambda *args: (_ for _ in ()).throw(ValueError("fail"))
    )
    with pytest.raises(ValueError):
        talk(session, "пошел нахер")
    assert session.to_dict() == before


def test_actual_v8_fixture_preserves_prose_original_input_and_rng_without_retrospective_socials(
    tmp_path,
):
    raw = (Path(__file__).parent / "fixtures/save-v8.json").read_bytes()
    (tmp_path / "slot-1.json").write_bytes(raw)
    slots = SaveSlots(tmp_path)
    old = slots.load(1)
    assert all(turn.origin == "legacy" and turn.dialogue is None for turn in old.turns)
    assert old.turns[0].action == "Спрашиваю жительницу о помощи"
    assert old.narrations[-1].prompt_version == "narrator-prose-3"
    assert (tmp_path / "slot-1.json").read_bytes() == raw
    assert old.submit("бросить кубик").roll.value == 1
    talk(old, "пошел нахер")
    assert grievance(old.turns, "villager") == 1
    slots.save(2, old)
    assert json.loads((tmp_path / "slot-2.json").read_bytes())["schema_version"] == 9
    assert slots.load(2).to_dict() == old.to_dict()
    assert (tmp_path / "slot-1.json").read_bytes() == raw


def test_user_text_kept_quick_command_hidden_and_stays_hidden_after_load(window):
    window.action_input.setText("осмотреться")
    window.submit_action()
    window._run_command("осмотреться")
    assert window.journal.toPlainText().count("Вы: осмотреться") == 1
    assert [t.origin for t in window._session.turns] == ["typed", "quick"]
    window.save_slot(1)
    window._session = window._saves.load(1)
    window._render_journal()
    assert window.journal.toPlainText().count("Вы: осмотреться") == 1


def test_narrator_label_and_quoted_npc_colour_survive_hostility_and_theme(window, qt_app):
    session = window._session
    talk(session, "Жительница, что делаешь тут?")
    frame = build_frame(session)
    session.add_narration(
        Narration(
            1, "local-test:1", "Жительница подняла голову. «Яблоки собираю».", frame.fingerprint
        )
    )
    window._render_journal()
    text = window.journal.toPlainText()
    assert "Рассказчик:" in text
    assert "ИИ-рассказчик" not in text and "· ИИ" not in text
    assert "Описывает результат" not in text
    window._run_command("поссориться с жительницей")
    qt_app.processEvents()
    block = window.journal.document().firstBlock()
    found = False
    while block.isValid():
        if "«Яблоки собираю»" in block.text():
            colors = {item.format.foreground().color().name() for item in block.layout().formats()}
            assert window.journal.actor_colour("villager").name() in colors
            assert window.journal.highlighter.colour("narrator").name() in colors
            found = True
        block = block.next()
    assert found


@pytest.mark.parametrize(
    "text",
    [
        "Путник решил написать поручение.",
        "Путник понял, что хочет помочь.",
        "Ворота отбрасывают тень. Вокруг всё живо.",
    ],
)
def test_dialogue_rejects_player_decisions_and_scenery_without_reply(text):
    session = Session(seed=42)
    talk(session, "что ты тут делаешь?")
    frame = build_frame(session)
    with pytest.raises(ValueError):
        parse_narration(
            {"message": {"role": "assistant", "content": json.dumps({"narration": text})}},
            frame,
            "local-test:1",
            dialogue_context(session),
        )
