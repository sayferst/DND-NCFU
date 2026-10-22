"""Independent engine and real Qt/HTTP delivery tests; no actual model inference."""

from copy import deepcopy

import pytest
from response_cases import context_for, new_session
from test_local_narrator import wait_for
from test_routerai import configure, router_server

from rpg_vkr.application import Session
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


def test_truthful_wallet_balance_is_information_not_a_reward():
    from response_cases import response

    from rpg_vkr.narrative.story import story_proposal

    session = new_session()
    message = "сколько у меня денег?"
    proposal = story_proposal(
        response(f"В вашем кошельке {session.world.gold} золотых."),
        build_frame(session),
        message,
        context=context_for(session, message),
    )
    assert proposal.narration


def test_spending_does_not_authorize_an_equal_reward():
    from rpg_vkr.domain.world import WorldState

    session = Session(world=WorldState(location="market", market_known=True, trading=True))
    session.submit("купить бинт")
    context = context_for(session, "что произошло?", confirmed=True)
    check_story_quality(
        "Вы потратили 3 золотые монеты.", build_frame(session), "что произошло?", campaign=context
    )
    with pytest.raises(NarrativeConflict):
        check_story_quality(
            "Вы получили 3 золотые монеты.",
            build_frame(session),
            "что произошло?",
            campaign=context,
        )


def test_long_scene_repair_keeps_adequate_token_budget():
    from rpg_vkr.narrative.story import repair_payload, story_payload

    session = new_session()
    payload = story_payload(
        build_frame(session), "deepseek/test", "Мастер, опиши подробно сцену", campaign={}
    )
    repair = repair_payload(payload, "достигнут лимит генерации")
    assert repair["options"]["num_predict"] >= payload["options"]["num_predict"]
    assert repair["options"]["num_predict"] <= 6000


def test_generated_npc_cannot_speak_directly_after_hero_leaves():
    from response_cases import response

    from rpg_vkr.narrative.story import story_payload, story_proposal

    session = new_session()
    session.submit_interaction("иду в галерею", WorldPlan((Step("move", "gallery"),)))
    context = context_for(session, "осмотрюсь")
    with pytest.raises(NarrativeConflict):
        story_proposal(
            response("Веста отвечает: «Здравствуй»."),
            build_frame(session),
            "осмотрюсь",
            context=context,
        )
    from rpg_vkr.narrative.master import campaign_context

    payload = story_payload(
        build_frame(session), "deepseek/test", "осмотрюсь", campaign=campaign_context(session)
    )
    # Validator-only roster cannot leak names/positions from remote or hidden places.
    assert "validation_roster" not in str(payload["messages"])


def test_new_npc_social_memory_reaches_writer_without_changing_catalog():
    from response_cases import MODEL

    from rpg_vkr.domain.director import Proposal
    from rpg_vkr.narrative.story_prompt import render_context

    session = new_session()
    before = session.catalog
    session.submit_scene(
        "Веста, ты дура",
        Proposal("", "vesta", "Веста хмурится. «Не грубите».", ()),
        MODEL,
        base_turn=0,
    )
    context = context_for(session, "Веста, извини")
    actor = next(a for a in context["turn_brief"]["actors"] if a["id"] == "vesta")
    assert actor["social_memory"]["grievance"] == 1
    assert "Память общения собеседника" in render_context(context)
    assert session.catalog == before


@pytest.mark.parametrize(
    "message", ["Говорю Весте спасибо и иду в галерею.", "Иду в галерею. Кто там?"]
)
def test_speech_followed_by_explicit_movement_binds_without_discarding_action(message):
    session = new_session()
    session.submit_interaction(message, WorldPlan((Step("move", "gallery"),)))
    assert session.current_place_id == "gallery"


def test_unmodeled_condition_requires_explicit_confirmation_instead_of_fake_evaluation():
    from rpg_vkr.domain.interactions import PlanConfirmationRequired

    session = new_session()
    plan = WorldPlan((Step("move", "gallery"),))
    before = deepcopy(session.to_dict())
    with pytest.raises(PlanConfirmationRequired):
        session.submit_interaction("иду в галерею, если она открыта", plan)
    assert session.to_dict() == before
    session.submit_interaction("иду в галерею, если она открыта", plan, confirmed_plan=True)
    assert session.current_place_id == "gallery"


def test_quoted_action_and_hypothesis_cannot_become_movement():
    session = new_session()
    for text in ["говорю: «иду в галерею и беру камень»", "если я пойду в галерею"]:
        with pytest.raises(ValueError):
            session.submit_interaction(text, WorldPlan((Step("move", "gallery"),)))
    assert session.current_place_id == "landing"
