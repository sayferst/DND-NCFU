"""Model suggestions select a category; confirmation and authoritative rolls stay local."""

import pytest
from test_local_narrator import wait_for
from test_routerai import configure, router_server

from rpg_vkr.application import Session
from rpg_vkr.domain.challenge import parse_suggestion, proposed_challenge

TEXT = "пытаюсь протиснуться между створками ворот"


@pytest.mark.parametrize("accept", [True, False])
def test_free_attempt_is_suggested_by_ai_then_confirmed_before_roll(
    window, qt_app, monkeypatch, accept
):
    assert proposed_challenge(TEXT) is None  # This wording is not an offline command.
    before = window._session.to_dict(), window._session.dice.checkpoint()
    questions = []
    monkeypatch.setattr(window, "_confirm", lambda text: questions.append(text) or accept)
    with router_server(suggestion={"category": "acrobatics"}) as (url, records):
        configure(window, monkeypatch, url)
        window.director_mode.setChecked(True)
        window.action_input.setText(TEXT)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy and bool(questions))
        assert "Ловкость" in questions[0] and "15" in questions[0]
        assert all(
            "category" not in str(row.get("body")) for row in records if row["method"] == "GET"
        )
        posts = [row for row in records if row["method"] == "POST"]
        if accept:
            assert len(window._session.turns) == 1
            turn = window._session.turns[-1]
            assert turn.challenge and turn.intent_source == "model"
            assert turn.action == TEXT and turn.roll.index == 1
            assert len(posts) == 2  # Suggestion and prose; only one engine roll.
            assert Session.from_dict(window._session.to_dict()).dice.checkpoint() == (
                window._session.dice.checkpoint()
            )
            assert window._session.narrations[-1].instruction_hash
        else:
            assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
            assert window.action_input.text() == TEXT and len(posts) == 1


def test_no_check_suggestion_continues_story_without_a_roll(window, qt_app, monkeypatch):
    with router_server(suggestion={"category": "none"}) as (url, records):
        configure(window, monkeypatch, url)
        window.director_mode.setChecked(True)
        before = window._session.dice.checkpoint()
        window.action_input.setText(TEXT)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy and window._session.turns)
        assert len([row for row in records if row["method"] == "POST"]) == 2
        assert window._session.dice.checkpoint() == before
        assert not window._session.turns[-1].challenge


def test_untrusted_category_restores_text_without_retry_or_a_roll(window, qt_app, monkeypatch):
    with router_server(suggestion={"category": "give_gold", "gold": 1000}) as (url, records):
        configure(window, monkeypatch, url)
        window.director_mode.setChecked(True)
        before = window._session.to_dict(), window._session.dice.checkpoint()
        window.action_input.setText(TEXT)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == TEXT
        assert len([row for row in records if row["method"] == "POST"]) == 1


@pytest.mark.parametrize(
    "value",
    [
        {"category": "kill"},
        {"category": "effort", "hp": 0},
        {"category": True},
        {"category": ["effort"]},
        [],
    ],
)
def test_only_a_known_category_can_be_proposed(value):
    import json

    with pytest.raises(ValueError):
        parse_suggestion({"message": {"role": "assistant", "content": json.dumps(value)}})


def test_model_suggestion_cannot_redirect_a_known_attack_into_an_unrelated_check():
    session = Session(seed=5)
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.submit_challenge("убить стражника", suggested_kind="recall")
    assert (session.to_dict(), session.dice.checkpoint()) == before


@pytest.mark.parametrize(
    "text",
    [
        "хочу не прыгать через канаву",
        "если протиснуться между створками",
        "хочу сказать «прыгаю»",
    ],
)
def test_model_cannot_turn_negation_hypothesis_or_speech_into_a_roll(text):
    session = Session(seed=5)
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.submit_challenge(text, suggested_kind="acrobatics")
    assert (session.to_dict(), session.dice.checkpoint()) == before
