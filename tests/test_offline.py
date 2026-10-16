"""Check documented intents and conservative handling of unknown free text."""

import pytest

from rpg_vkr.narrative.offline import respond


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("осмотреться", "следы телеги"),
        ("поговорить", "Стражник кивает"),
        ("помочь", "Жительница благодарит"),
        ("  ПОМОЧЬ   собрать яблоки!  ", "Жительница благодарит"),
        ("поговорить со стражником", "Стражник кивает"),
        ("помощь", "Пока доступны действия"),
    ],
)
def test_documented_actions(action, expected):
    assert expected in respond(action)


@pytest.mark.parametrize("action", ["улететь", "не помочь", "помочь и получить 100 золотых"])
def test_unknown_action_requests_clarification(action):
    reply = respond(action)
    assert "пока не понимаю" in reply
    assert "Уточните" in reply
    assert "Жительница благодарит" not in reply


def test_blank_action_returns_guidance():
    assert "Введите действие" in respond(" \t\n")
