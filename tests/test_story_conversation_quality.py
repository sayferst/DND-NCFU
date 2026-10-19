"""Regressions from user Qwen output; synthetic responses do not establish LLM quality."""

import json
from pathlib import Path

import pytest
from test_local_narrator import local_server, wait_for

from rpg_vkr.application import Session
from rpg_vkr.domain.director import StoryFact, known_facts
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import last_interlocutor
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import payload_context, story_payload, story_proposal
from rpg_vkr.narrative.story_quality import check_story_quality
from rpg_vkr.storage.knowledge import CampaignIndex, export_session, restore_session, retrieve
from rpg_vkr.storage.slots import SaveSlots

ROOT = Path(__file__).resolve().parents[1]


def response(text):
    return {"message": {"role": "assistant", "content": text}}


def request_context(session, text):
    return payload_context(
        story_payload(
            build_frame(session),
            "qwen3:1.7b",
            text,
            memory=retrieve(session, text),
            campaign=campaign_context(session, last_interlocutor(session)),
        )
    )


def test_actual_qwen_response_is_rejected_instead_of_technical_ok():
    sample = json.loads(
        (ROOT / "docs/validation/windows-qwen-repetition-2026-10-19.json").read_text(
            encoding="utf-8"
        )
    )
    session = Session(seed=42)
    before = session.to_dict(), session.dice.checkpoint()
    context = request_context(session, sample["input"])
    assert context["turn_brief"]["target_id"] == "villager"
    assert context["turn_brief"]["topics"] == ["help", "name"]
    with pytest.raises(ValueError, match="мысли, чувства"):
        story_proposal(
            response(sample["response"]), build_frame(session), sample["input"], context=context
        )
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_actual_v13_bad_prose_loads_but_is_not_fed_back_as_world_fact(tmp_path):
    path = ROOT / "tests/fixtures/save-v13.json"
    raw = path.read_bytes()
    data = json.loads(raw)
    session = Session.from_dict(data["session"], version=13)
    assert session.character.name == "Путана"
    assert session.narrations[0].prompt_version == "narrator-prose-8"
    assert "мунданию" in session.turns[0].text
    context = payload_context(
        story_payload(
            build_frame(session),
            "qwen3:1.7b",
            "спросить, как у нее дела",
            memory=retrieve(session, "мунданию ее помощь"),
            history=[
                {
                    "player": session.turns[0].action,
                    "result": session.turns[0].text,
                    "source": "scene-director-2",
                }
            ],
        )
    )
    encoded = json.dumps(context, ensure_ascii=False)
    assert "мунданию" not in encoded and "Вы замолчите" not in encoded
    assert "confirmed_result" not in context["current_scene"]
    assert context["recent_events"][0]["player_message"] == session.turns[0].action
    index = CampaignIndex(session)
    try:
        assert "мунданию" in index.db.execute("SELECT result FROM events").fetchone()[0]
    finally:
        index.close()
    store = SaveSlots(tmp_path)
    store.save(1, session)
    assert store.load(1).to_dict() == session.to_dict()
    assert session.submit("бросить кубик").roll.value == 4
    assert path.read_bytes() == raw


def test_pronoun_uses_visible_interlocutor_and_all_questions_are_answered(tmp_path):
    session = Session(seed=42)
    text = "подойду к девушке"
    context = request_context(session, text)
    value = story_proposal(
        response("Вы подходите к женщине с яблоками. «Здравствуйте», — отзывается она."),
        build_frame(session),
        text,
        context=context,
    )
    session.submit_scene(text, value, "test:1", base_turn=0)
    assert last_interlocutor(session) == "villager"
    text = "спросить, как у нее дела, нужна ли ей помощь, а заодно узнать ее имя"
    context = request_context(session, text)
    brief = context["turn_brief"]
    assert brief["topics"] == ["wellbeing", "help", "name"]
    assert len(brief["tasks"]) == 3
    assert brief["target_id"] == "villager"
    assert len(context["memory"]["npcs"]) == 1
    name = brief["public_name"]
    for incomplete in (
        "Женщина придерживает корзину. «Что-то случилось?»",
        f"Женщина поправляет ручку корзины. «Хорошо, спасибо. Я {name}».",
        "Женщина кивает. «Держусь, спасибо. Поможете собрать яблоки?»",
    ):
        with pytest.raises(ValueError, match="Не отвечено"):
            story_proposal(response(incomplete), build_frame(session), text, context=context)
    value = story_proposal(
        response(
            f"Женщина отодвигает корзину от дороги. «Меня зовут {name}. "
            "Дела так себе: яблоки рассыпались. Если поможете собрать их, буду благодарна»."
        ),
        build_frame(session),
        text,
        context=context,
    )
    assert value.focus_id == "villager"
    assert value.facts == (StoryFact("villager", "public_name", name),)
    checkpoint = session.world, session.dice.checkpoint()
    session.submit_scene(text, value, "test:1", base_turn=1)
    assert (session.world, session.dice.checkpoint()) == checkpoint
    assert session.world.quest == "available"
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    restored = slots.load(1)
    db_path = tmp_path / "campaign.sqlite3"
    export_session(restored, db_path)
    restored = restore_session(db_path)
    assert known_facts(restored.turns)["villager", "public_name"] == name
    again = request_context(restored, "как тебя зовут?")
    assert again["turn_brief"]["public_name"] == name
    assert again["turn_brief"]["name_established"]
    by_name = request_context(restored, name + ", как дела?")
    assert by_name["turn_brief"]["target_id"] == "villager"
    assert restored.submit("бросить кубик").roll.value == 4


@pytest.mark.parametrize("input_text", ["подойду", "спросить, как дела"])
def test_ambiguous_target_is_clarified_locally_without_network(window, qt_app, input_text):
    window.director_mode.setChecked(True)
    window.ollama.models = ("qwen3:1.7b",)
    window.local_model.addItem("qwen3:1.7b")
    window.enable_local_narrator.setChecked(True)
    before = window._session.world, window._session.dice.checkpoint()
    window.action_input.setText(input_text)
    window.send_button.click()
    assert not window.ollama.busy
    assert len(window._session.turns) == 1
    assert window._session.turns[-1].scene.model == "local-clarification"
    assert "стражнику" in window._session.turns[-1].text
    assert "женщине" in window._session.turns[-1].text
    assert (window._session.world, window._session.dice.checkpoint()) == before


@pytest.mark.parametrize(
    "answer,player_input",
    [
        ("Вы замолчали, не зная, что сказать. Женщина ждёт ответа.", "как дела у девушки?"),
        ("Вы чувствуете необъяснимую нежность к девушке у ворот.", "подойти к девушке"),
        ("Вы решили помочь женщине и согласились взять её корзину.", "спросить про работу"),
        ("На вашем поясе висит кинжал с широкой рукоятью.", "осмотреться"),
    ],
)
def test_invented_player_agency_and_equipment_are_rejected(answer, player_input):
    with pytest.raises(ValueError):
        check_story_quality(answer, build_frame(Session(seed=42)), player_input)


def test_requested_silence_and_npc_feelings_are_allowed():
    check_story_quality(
        "Вы замолчали. Женщина ждёт у корзины.", build_frame(Session(seed=42)), "я молча жду"
    )
    check_story_quality(
        "Женщина хмурится. «Вы чувствуете холод? Я немного замёрзла».",
        build_frame(Session(seed=42)),
        "как дела?",
    )


def test_repeats_between_turns_and_within_answer_are_detected():
    text = (
        "Женщина с яблоками поправляет корзину и смотрит на дорогу за воротами. «Что-то случилось?»"
    )
    frame = build_frame(Session(seed=42))
    with pytest.raises(ValueError, match="повторяет|Скопировано"):
        check_story_quality(text, frame, "как дела?", previous=[{"result": text}])
    with pytest.raises(ValueError, match="повторяется"):
        check_story_quality(text + "\n" + text, frame, "как дела?")
    check_story_quality(text, frame, "повтори описание", previous=[{"result": text}])


def test_real_http_semantic_rejection_gets_one_targeted_repair(window, qt_app):
    window.director_mode.setChecked(True)
    with local_server(mode="plain_semantic_first") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("подойду к девушке и спрошу, как у нее дела")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 3
        assert len(window._session.turns) == 1
        assert "мысли, чувства" in requests[2][1]["messages"][0]["content"]
        assert "Попытка 2" in window.ollama.last_diagnostic
        assert "литературное качество не оценено" in window.ollama.last_diagnostic
        assert "Вы замолчите" not in window._session.turns[0].text


def test_two_semantically_bad_answers_do_not_enter_memory(window, qt_app):
    window.director_mode.setChecked(True)
    with local_server(mode="plain_semantic_bad") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.to_dict(), window._session.dice.checkpoint()
        text = "подойду к девушке и спрошу, как у нее дела"
        window.action_input.setText(text)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 3
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == text


def test_senses_and_other_characters_equipment_are_not_player_agency():
    frame = build_frame(Session(seed=42))
    for text in (
        "Вы чувствуете запах спелых яблок. У ворот слышны шаги.",
        "У стражника на поясе висит нож. Он поглядывает на дорогу.",
        "Вы понимаете, откуда доносится шум: на площади идёт торг.",
    ):
        check_story_quality(text, frame, "осматриваю окрестности и ищу источник шума")


def test_repair_feedback_reports_all_missing_topics_not_just_first_defect():
    from rpg_vkr.narrative.story import repair_payload

    sample = json.loads(
        (ROOT / "docs/validation/windows-qwen-repetition-2026-10-19.json").read_text(
            encoding="utf-8"
        )
    )
    session = Session(seed=42)
    payload = story_payload(build_frame(session), "qwen3:1.7b", sample["input"])
    with pytest.raises(ValueError) as captured:
        story_proposal(
            response(sample["response"]),
            build_frame(session),
            sample["input"],
            context=payload_context(payload),
        )
    repaired = repair_payload(payload, captured.value)
    instruction = repaired["messages"][0]["content"]
    assert "мысли, чувства" in instruction
    assert "снаряжение" in instruction
    assert "Не отвечено на вопрос об имени" in instruction
    assert "нужна ли помощь" in instruction
    assert len(payload["messages"]) == len(repaired["messages"]) == 2


def test_committed_name_is_immutable_and_accepts_inflected_address():
    from rpg_vkr.domain.director import Proposal

    session = Session(seed=42)
    session.submit_scene(
        "узнать ее имя",
        Proposal(
            "",
            "villager",
            "«Я Марта», — говорит женщина с корзиной.",
            (StoryFact("villager", "public_name", "Марта"),),
        ),
        "test:1",
        base_turn=0,
    )
    context = request_context(session, "подойти к Марте и спросить, как дела")
    assert context["turn_brief"]["target_id"] == "villager"
    assert context["turn_brief"]["name_established"]
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="установленный факт"):
        session.submit_scene(
            "как тебя зовут?",
            Proposal(
                "",
                "villager",
                "«Я Дарина», — отвечает женщина с корзиной.",
                (StoryFact("villager", "public_name", "Дарина"),),
            ),
            "test:1",
            base_turn=1,
        )
    assert (session.to_dict(), session.dice.checkpoint()) == before
