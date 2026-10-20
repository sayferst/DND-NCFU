"""Independent engine and real Qt/HTTP delivery tests; no actual model inference."""

from copy import deepcopy

import pytest
from response_cases import context_for, new_session
from test_local_narrator import wait_for
from test_routerai import configure, router_server

from rpg_vkr.domain.interactions import Step, WorldPlan, bind_plan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.failures import NarrativeConflict, classify
from rpg_vkr.narrative.story_quality import check_story_quality
from rpg_vkr.storage.slots import SaveSlots

ASSESSMENT = {"ability": "intelligence", "dc": 12, "purpose": "оценить устройство подъёмника"}


def test_generic_check_is_replayable_without_implicit_rewards(tmp_path):
    session = new_session()
    before = session.world, session.character, session.interactive_world
    turn = session.submit_challenge("оцениваю устройство подъёмника", assessment=ASSESSMENT)
    assert turn.challenge.kind == "general" and turn.check.ability == "intelligence"
    assert (session.world, session.character, session.interactive_world) == before
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    loaded = slots.load(1)
    assert loaded.to_dict() == session.to_dict()
    assert loaded.dice.checkpoint() == session.dice.checkpoint()
    assert loaded.dice.roll_d20() == session.dice.roll_d20()


@pytest.mark.parametrize("change", [{"dc": 100}, {"ability": "gold"}, {"purpose": ""}])
def test_invalid_generic_check_is_atomic(change):
    session = new_session()
    before = deepcopy(session.to_dict()), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.submit_challenge("оцениваю механизм", assessment=ASSESSMENT | change)
    assert (session.to_dict(), session.dice.checkpoint()) == before


@pytest.mark.parametrize("text", ["не иду в галерею", "могу ли пойти в галерею?", "говорю: «иду»"])
def test_binding_preserves_real_negation_question_and_quoted_speech(text):
    with pytest.raises(ValueError):
        bind_plan(text, WorldPlan((Step("move", "gallery"),)))


def test_incidental_negation_is_not_a_veto_on_movement():
    session = new_session()
    turn = session.submit_interaction(
        "иду в галерею, не оглядываясь", WorldPlan((Step("move", "gallery"),))
    )
    assert turn.interaction and session.current_place_id == "gallery"


@pytest.mark.parametrize("after_roll", [False, True])
def test_an_unrelated_receipt_never_authorizes_numeric_rewards(after_roll):
    session = new_session()
    if after_roll:
        session.submit_challenge("оцениваю механизм", assessment=ASSESSMENT)
    context = context_for(session, "что получилось?", confirmed=after_roll)
    with pytest.raises(NarrativeConflict):
        check_story_quality(
            "Вы получили 100 золотых.", build_frame(session), "что получилось?", campaign=context
        )


def test_new_npc_conversation_needs_one_model_post_and_survives_restart(
    window, qt_app, monkeypatch, tmp_path
):
    window._session = new_session()
    plans = {
        "Веста, здравствуйте": {
            "steps": [],
            "places": [],
            "check": "none",
            "dialogue_target": "vesta",
            "reply": "Веста кивает. «Здравствуйте».",
        },
        "Как тебя зовут?": {
            "steps": [],
            "places": [],
            "check": "none",
            "dialogue_target": "vesta",
            "reply": "«Веста», — отвечает картограф.",
        },
    }
    with router_server(world_plans=plans) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        for count, message in enumerate(plans, 1):
            window.action_input.setText(message)
            window.send_button.click()
            wait_for(qt_app, lambda: not window.ollama.busy)
            assert len(window._session.turns) == count
            assert window._session.turns[-1].actor_id == "vesta"
            assert len([c for c in calls if c["method"] == "POST"]) == count
        slots = SaveSlots(tmp_path)
        slots.save(1, window._session)
        loaded = slots.load(1)
        assert loaded.to_dict() == window._session.to_dict()


def test_unsupported_action_receives_explanation_without_fake_success(window, qt_app, monkeypatch):
    window._session = new_session()
    message = "превращаю каменный мост в облако"
    reply = "Камень остаётся камнем: у вас пока нет заклинания для такого превращения."
    plan = {
        "steps": [],
        "places": [],
        "check": "none",
        "reply": reply,
        "obstacle": "Нет известного заклинания",
    }
    before = (
        window._session.world,
        window._session.interactive_world,
        window._session.dice.checkpoint(),
    )
    with router_server(world_plans={message: plan}) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(message)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert window._session.narrations[-1].text == reply
        assert (
            window._session.world,
            window._session.interactive_world,
            window._session.dice.checkpoint(),
        ) == before
        assert len([c for c in calls if c["method"] == "POST"]) == 1


def test_invalid_plan_can_explain_without_executing_any_operation(window, qt_app, monkeypatch):
    window._session = new_session()
    message = "пробую необычное заклинание"
    reply = "Сила не отзывается. Нужно понять, какой источник магии здесь доступен."
    with router_server(
        world_plans={message: {"steps": [{"op": "give_gold"}]}}, writer_text=reply
    ) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        before = window._session.world, window._session.dice.checkpoint()
        window.action_input.setText(message)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert window._session.narrations[-1].text == reply
        assert (window._session.world, window._session.dice.checkpoint()) == before
        assert len([c for c in calls if c["method"] == "POST"]) == 2


@pytest.mark.parametrize(
    "error,options,expected",
    [
        (NarrativeConflict("false outcome"), {}, "canon_conflict"),
        (ValueError("format"), {}, "invalid_format"),
        (ValueError("cut"), {"data": {"done_reason": "length"}}, "token_limit"),
        (ValueError("server"), {"status": 503}, "network"),
        (ValueError("balance"), {"status": 402}, "access_or_budget"),
    ],
)
def test_failure_categories_are_distinct(error, options, expected):
    assert classify(error, stage="director", **options)["code"] == expected
