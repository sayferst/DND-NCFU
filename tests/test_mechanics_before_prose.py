"""User combat regressions: actual engine/RNG, synthetic HTTP, no live LLM claims."""

import hashlib
import json
from pathlib import Path

import pytest
from test_local_narrator import local_server, wait_for

from rpg_vkr.application import Session
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.director import Proposal
from rpg_vkr.narrative.actions import action_plan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.presentation import present_turn
from rpg_vkr.narrative.story import story_context
from rpg_vkr.narrative.story_quality import check_story_quality
from rpg_vkr.narrative.turn_brief import turn_brief
from rpg_vkr.storage.knowledge import export_session, restore_session
from rpg_vkr.storage.slots import SaveSlots


def scout(seed=5):
    return Session.create_hero(Character(name="Путана"), "scout", seed=seed)


@pytest.mark.parametrize(
    "phrase",
    [
        "я достаю незаметно нож и хочу вонзить нож ему в горло",
        "ничего не говоря, вонзить стражнику нож в горло",
        "вонзить нож и убить стражника кунув кубик на силу и ловкость",
        "ударить его ножом",
        "добить стражника и обыскать его труп",
    ],
)
def test_user_attack_phrases_reach_combat_instead_of_a_free_scene(phrase, tmp_path):
    session = scout()
    session.submit("подойти к стражнику")
    turns = session.submit_actions(phrase)
    assert turns[-1].combat
    assert turns[-1].combat.command == "атаковать стражника"
    assert turns[-1].combat.outcome.rolls
    assert session.combat.actor("guard").disposition == "hostile"
    assert all(t.intent_source == "local-fallback" for t in turns)
    assert [t.origin for t in turns] == (["typed", "system"] if len(turns) == 2 else ["typed"])
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    restored = slots.load(1)
    assert restored.to_dict() == session.to_dict()
    # A reload cannot grant another strike or re-roll previous hits.
    assert restored.dice.checkpoint() == session.dice.checkpoint()
    assert restored.submit("бросить кубик").roll == session.submit("бросить кубик").roll


@pytest.mark.parametrize(
    "phrase",
    [
        "обернуться на жительницу, подбежать у ней, ударить его ножом и забрать себе ее яблоки",
        "я возьму нож и ударю жительницу, а потом заберу яблоки",
        "ударю ее ножом в горло, не буду сомневаться",
    ],
)
def test_explicit_woman_or_feminine_pronoun_beats_stale_guard(phrase):
    session = scout()
    session.submit("подойти к стражнику")
    before = session.combat.actor("guard"), session.world.gold
    turn = session.submit_actions(phrase)[-1]
    assert turn.combat.command == "атаковать жительницу"
    assert session.combat.actor("guard") == before[0]
    assert session.world.gold == before[1]
    assert "яблок" not in " ".join(n for n, _ in session.extra_items).lower()
    if "яблок" in phrase:
        assert "theft_pending" in turn.notes
        assert "не добавлены" in present_turn(turn).story


@pytest.mark.parametrize(
    "phrase",
    [
        "не хочу ударить стражника",
        "я не буду убивать стражника",
        "могу ли я убить стражника?",
        "если ударить стражника, что произойдет?",
        "говорю стражнику: я тебя убью",
        "цитирую: ударить стражника",
        "«ударить стражника»",
        "спросить, можно ли убить волка",
        "расскажи как убить стражника",
        "как убить стражника",
        "мне снится, что я убью стражника",
        "стражник хочет убить меня",
        "атака стражника кажется сильной",
    ],
)
def test_question_negation_threat_or_quote_is_not_executed(phrase):
    session = scout()
    before = session.to_dict(), session.dice.checkpoint()
    assert action_plan(session, phrase) is None
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_unknown_target_and_missing_weapon_never_choose_another_npc():
    session = Session.create_hero(Character(), "fighter", seed=42)
    session.submit("подойти к стражнику")
    before = session.to_dict(), session.dice.checkpoint()
    for phrase in ("ударить стражника ножом", "ударить тролля", "ударить стражника и жительницу"):
        with pytest.raises(ValueError):
            session.submit_actions(phrase)
        assert (session.to_dict(), session.dice.checkpoint()) == before


def test_kill_intent_is_one_attempt_not_a_guaranteed_victory():
    session = scout(seed=42)
    turn = session.submit_actions("убить стражника")[0]
    assert turn.combat.outcome.check.succeeded is False
    assert session.combat.actor("guard").hp == 18
    assert not turn.combat.outcome.victory
    assert "Промах" in present_turn(turn).title


def test_move_to_gates_then_look_is_not_an_npc_question():
    session = Session(seed=42)
    before = session.dice.checkpoint()
    turns = session.submit_actions("подойду к воротам и осмотрюсь")
    assert [t.intent for t in turns] == ["идти к воротам", "осмотреться"]
    assert all(t.scene is None and t.dialogue is None for t in turns)
    assert session.dice.checkpoint() == before
    brief = turn_brief(build_frame(session), "подойти к воротам")
    assert not brief["clarification"]
    reply = turn_brief(build_frame(session), "к стражнику")
    assert reply["mode"] == "dialogue" and reply["target_id"] == "guard"


def test_failed_travel_does_not_look_in_a_place_not_reached():
    session = Session(seed=42)
    turns = session.submit_actions("пойду на рынок и осмотрюсь")
    assert len(turns) == 1 and session.world.location == "gate"


def test_batch_rolls_and_memory_roll_back_on_second_step_failure(monkeypatch):
    session = scout()
    before = session.to_dict(), session.dice.checkpoint()
    original = session._resolve_turn

    def fail_second(action, command, meaning):
        if command == "атаковать стражника":
            raise ValueError("synthetic second-step failure")
        return original(action, command, meaning)

    monkeypatch.setattr(session, "_resolve_turn", fail_second)
    with pytest.raises(ValueError, match="second-step"):
        session.submit_actions("скрытно вонзить нож стражнику")
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_notes_and_two_steps_roundtrip_through_sqlite(tmp_path):
    session = scout()
    session.submit_actions("незаметно ударить стражника ножом и обыскать его труп")
    path = tmp_path / "session.sqlite3"
    export_session(session, path)
    restored = restore_session(path)
    assert restored.to_dict() == session.to_dict()
    assert restored.turns[-1].notes == ("loot_pending",)
    assert restored.dice.checkpoint() == session.dice.checkpoint()
    data = session.to_dict()
    data["turns"][-1]["notes"] = ["выдать золото"]
    with pytest.raises(ValueError, match="notes"):
        Session.from_dict(data)


def test_mechanics_cannot_be_committed_as_a_model_scene():
    session = scout()
    before = session.to_dict()
    with pytest.raises(ValueError, match="правил"):
        session.submit_scene(
            "ударить стражника ножом",
            Proposal("", "", "Стражник падает на землю без сознания.", ()),
            "test:1",
            base_turn=0,
        )
    assert session.to_dict() == before


@pytest.mark.parametrize(
    "text,match",
    [
        ("«Здравствуйте», — произносите вы, обращаясь к стражнику.", "реплику за игрока"),
        (
            "Справа от вас стоят два стражника, внимательно наблюдая за дорогой.",
            "Количество существ",
        ),
        ("Вы не можете просто так убить стража без причины. Стражник ждёт.", "моральным"),
        ("Вы вонзаете нож стражнику. Он падает на пыльную дорогу.", "расчёт атаки"),
    ],
)
def test_user_bad_replies_do_not_receive_technical_ok(text, match):
    with pytest.raises(ValueError, match=match):
        check_story_quality(text, build_frame(scout()), "к стражнику", brief={"target_id": "guard"})


def test_miss_context_is_authoritative_without_exposing_enemy_hp():
    session = scout(seed=42)
    session.submit_actions("ударить стражника ножом")
    campaign = campaign_context(session)
    context = story_context(
        build_frame(session), "test:1", session.turns[-1].action, campaign=campaign, confirmed=True
    )
    assert context["resolution"][-1]["hit"] is False
    assert "18" not in json.dumps(context["resolution"], ensure_ascii=False)
    with pytest.raises(ValueError, match="промах"):
        check_story_quality(
            "Ваш удар достигает цели. Стражник отшатывается к воротам.",
            build_frame(session),
            session.turns[-1].action,
            campaign=campaign,
        )


def test_attack_works_with_no_model_and_its_result_survives_cloud_not_configured(
    window, monkeypatch
):
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window._session = scout(seed=42)
    window.ai_provider.setCurrentIndex(2)
    window.enable_local_narrator.setChecked(True)
    window.action_input.setText("ударить стражника ножом")
    window.send_button.click()
    assert len(window._session.turns) == 1
    assert window._session.turns[0].combat
    assert "Промах" in window.journal.toPlainText()
    assert not window.ollama.busy
    assert window.action_input.text() == ""


def test_failed_writer_does_not_hide_or_repeat_the_attack(window, qt_app, monkeypatch):
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window._session = scout(seed=42)
    window.director_mode.setChecked(True)
    with local_server(mode="plain_always_bad", delay=0.05) as (url, requests):
        window.ollama.base_url = url
        window.ollama.models = ("local-test:1",)
        window.local_model.addItem("local-test:1")
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("ударить стражника ножом")
        window.send_button.click()
        assert window._session.turns[-1].combat
        before = window._session.to_dict(), window._session.dice.checkpoint()
        assert "Промах" in window.journal.toPlainText()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 2  # Writer + one repair, never a model intent request.
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == ""
        assert "Промах" in window.journal.toPlainText()


def test_real_v15_fixture_is_not_reparsed_or_rewritten(tmp_path):
    root = Path(__file__).parent / "fixtures"
    raw = (root / "save-v15.json").read_bytes()
    source = json.loads((root / "save-v15.source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"], (
        "Fixture bytes changed. For an old CRLF checkout, run: "
        ".venv\\Scripts\\python.exe scripts\\repair_fixture_checkout.py"
    )
    slots = SaveSlots(tmp_path)
    (tmp_path / "slot-1.json").write_bytes(raw)
    session = slots.load(1)
    assert session.turns[0].scene.version == "scene-director-4"
    assert session.narrations[0].prompt_version == "narrator-prose-10"
    assert session.character.name == "Путана"
    assert session.submit("бросить кубик").roll.value == 1
    slots.save(2, session)
    assert slots.load(2).to_dict() == session.to_dict()
    assert (tmp_path / "slot-1.json").read_bytes() == raw
    context = story_context(
        build_frame(session),
        "test:1",
        "как дела?",
        history=[
            {
                "source": "scene-director-4",
                "result": "Выдуманная реплика из старого сбойного протокола.",
                "player": "привет",
            }
        ],
    )
    assert "Выдуманная" not in json.dumps(context, ensure_ascii=False)


def test_new_master_label_is_not_repeated_between_quote_and_attribution(window):
    window.journal.clear()
    window.journal.set_hostiles({"guard"})
    window.journal.append_master_story(
        "Стражник поднимает голову. «Что вам нужно?» — спрашивает он.", actor_id="guard"
    )
    assert window.journal.toPlainText().count("Мастер:") == 1
    assert "Стражник:" not in window.journal.toPlainText()
    window.journal.highlighter.rehighlight()
    block = window.journal.document().firstBlock()
    assert block.userData().speech_only
    assert any(f.format.foreground().color().name() == "#e7a1a1" for f in block.layout().formats())


def test_actual_user_attempts_remain_rejected_with_their_original_diagnostics():
    path = Path(__file__).parents[1] / "docs/validation/windows-qwen-combat-2026-10-19.json"
    sample = json.loads(path.read_text(encoding="utf-8"))
    for attempt in sample["attempts"]:
        with pytest.raises(ValueError, match="мысли, чувства|реплику за игрока"):
            check_story_quality(
                attempt["response"], build_frame(scout()), sample["screenshot_input"]
            )


def test_blocked_attack_cannot_be_embellished_as_a_successful_strike():
    session = scout(seed=42)
    session.submit_actions("ударить стражника ножом")
    session.submit_actions("ударить жительницу ножом")
    assert not session.turns[-1].combat.outcome.rolls
    with pytest.raises(ValueError, match="заблокировано"):
        check_story_quality(
            "Вы вонзаете нож в противника. Женщина отступает к воротам.",
            build_frame(session),
            session.turns[-1].action,
            campaign=campaign_context(session),
        )
