import pytest
from test_visual_controller import finish
from test_visual_controller import visual as _visual_fixture

from rpg_vkr.visuals.commands import visual_request

visual = _visual_fixture


@pytest.mark.parametrize(
    "text",
    [
        "Нарисуй этого персонажа",
        "Изобрази последнее событие",
        "Покажи этот предмет",
        "Пожалуйста, изобрази сцену",
    ],
)
def test_explicit_visual_requests(text):
    assert visual_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "я прошу художника нарисовать дом",
        "покажи инвентарь",
        "спрашиваю, где находится портрет",
        '"нарисуй NPC"',
    ],
)
def test_rpg_actions_not_misclassified(text):
    assert not visual_request(text)


def test_visual_chat_never_calls_text_master_or_changes_session(visual, monkeypatch):
    window, controller, fake = visual
    before = window._session.to_dict(), window._session.dice.checkpoint()
    monkeypatch.setattr(window.ollama, "plan_world", lambda *_: pytest.fail("Text model called"))
    window.action_input.setText("Изобрази сцену")
    window.submit_action()
    finish(controller)
    assert len(fake.posts) == 1
    assert before == (window._session.to_dict(), window._session.dice.checkpoint())
    assert not window.action_input.text()
