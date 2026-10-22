"""Confirmed free-form attempts use engine rolls, never model-created effects."""

from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.challenge import CHALLENGES, proposed_challenge
from rpg_vkr.domain.character import Character
from rpg_vkr.narrative.actions import action_plan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.presentation import present_turn
from rpg_vkr.narrative.story import story_payload
from rpg_vkr.storage.slots import SaveSlots


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Я хочу взобраться на стену", "climb"),
        ("пытаюсь поднять тяжёлый камень", "effort"),
        ("перепрыгну канаву", "acrobatics"),
        ("хочу выдержать холод", "endure"),
        ("расшифровываю надпись", "decipher"),
        ("вспомнить историю деревни", "recall"),
        ("прислушаюсь к шуму", "listen"),
        ("убеждаю стражника меня выслушать", "persuade"),
    ],
)
def test_attempts_produce_correct_checked_roll_and_replay_once(text, kind, tmp_path):
    session = Session(seed=5)
    before = session.world, session.combat, session.progress, session.character
    assert proposed_challenge(text) == kind
    turn = session.submit_challenge(text)
    ability, difficulty, _ = CHALLENGES[kind]
    assert turn.challenge and turn.roll.value == 20
    assert turn.check.ability == ability and turn.check.difficulty == difficulty
    assert turn.action == text and turn.check.succeeded
    assert turn.challenge.story() in present_turn(turn).story
    assert "Итого" in present_turn(turn).details and "Итого" not in present_turn(turn).story
    assert (session.world, session.combat, session.progress, session.character) == before
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    restored = slots.load(1)
    assert restored.to_dict() == session.to_dict()
    assert restored.dice.checkpoint() == session.dice.checkpoint()
    assert restored.dice.roll_d20() == session.dice.roll_d20()


@pytest.mark.parametrize(
    "text",
    [
        "Не хочу расшифровывать надпись",
        "Если перепрыгнуть канаву?",
        "Могу ли я взобраться на стену?",
        "Говорю: «поднять камень»",
        "«Перепрыгну канаву»",
        "Перепрыгну канаву и заберу золото",
        "Поднять камень; затем ударить стражника",
        "Убить стражника используя интеллект",
        "Куплю яблоки",
        "Перепрыгну канаву и пойду на рынок",
    ],
)
def test_speech_negation_and_combinations_do_not_silently_roll(text):
    session = Session(seed=5)
    before = session.to_dict(), session.dice.checkpoint()
    assert proposed_challenge(text) is None
    with pytest.raises(ValueError):
        session.submit_challenge(text)
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_roll_confirmation_can_be_declined_then_accepted_without_losing_input(window, monkeypatch):
    text = "хочу расшифровать надпись"
    window.action_input.setText(text)
    before = window._session.to_dict(), window._session.dice.checkpoint()
    questions = []
    monkeypatch.setattr(window, "_confirm", lambda question: questions.append(question) or False)
    window.submit_action()
    assert "Интеллект" in questions[0] and "15" in questions[0]
    assert window.action_input.text() == text
    assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window.submit_action()
    assert len(window._session.turns) == 1 and window._session.turns[0].challenge
    assert not window.action_input.text()
    assert "Итого" in window.roll_breakdown.toPlainText()


def test_challenge_does_not_bypass_active_combat_or_defeat():
    session = Session.create_hero(Character(), "scout", seed=42)
    session.submit_actions("вонзаю нож стражнику в горло")
    assert session.combat.active
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.submit_challenge("перепрыгну канаву")
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_recording_error_rolls_back_rng_and_history(monkeypatch):
    session = Session(seed=5)
    before = session.to_dict(), session.dice.checkpoint()

    def fail(*args):
        raise ValueError("synthetic recording error")

    monkeypatch.setattr(type(session.memory), "append", fail)
    with pytest.raises(ValueError, match="recording error"):
        session.submit_challenge("перепрыгну канаву")
    assert (session.to_dict(), session.dice.checkpoint()) == before


@pytest.mark.parametrize(
    "damage", ["roll", "total", "difficulty", "kind", "location", "score", "mixed", "bool"]
)
def test_tampered_challenge_is_rejected(damage):
    session = Session(seed=5)
    session.submit_challenge("расшифровать надпись")
    data = deepcopy(session.to_dict())
    turn = data["turns"][0]
    record = turn["challenge"]
    if damage == "roll":
        record["roll"]["value"] = 1
    elif damage == "total":
        record["check"]["total"] += 1
    elif damage == "difficulty":
        record["check"]["difficulty"] = 1
    elif damage == "kind":
        record["kind"] = "grant_gold"
    elif damage == "location":
        record["location"] = "market"
    elif damage == "score":
        record["check"]["score"] = 30
    elif damage == "mixed":
        turn["intent"] = "взять поручение"
    else:
        record["check"]["succeeded"] = 1
    with pytest.raises(ValueError):
        Session.from_dict(data)


@pytest.mark.parametrize(
    "text",
    [
        "вонзаю нож стражнику в горло",
        "я убиваю стражника ножом",
        "я хочу убить стражника описав как вонзаю ему в горло нож",
    ],
)
def test_attack_inflections_are_mechanics_even_with_ai_switched_off(text, window, monkeypatch):
    window._session = Session.create_hero(Character(), "scout", seed=42)
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    assert action_plan(window._session, text).target == "guard"
    window.action_input.setText(text)
    window.submit_action()
    assert window._session.turns[-1].combat
    assert window._session.combat.actor("guard").disposition == "hostile"
    assert "Бросок №" in window.roll_breakdown.toPlainText()


def test_writer_receives_attempt_and_result_without_a_second_roll():
    session = Session(seed=5)
    turn = session.submit_challenge("расшифровать надпись")
    before = session.dice.checkpoint()
    payload = story_payload(
        build_frame(session),
        "deepseek/deepseek-v4-pro-0813",
        turn.action,
        campaign=campaign_context(session),
        confirmed=True,
    )
    prompt = payload["messages"][1]["content"]
    assert turn.action in prompt and turn.challenge.story() in prompt
    assert "Не бросай кубик повторно" in prompt
    assert session.dice.checkpoint() == before
