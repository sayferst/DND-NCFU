"""Free-only request constraints and synthetic failure handling; no provider API calls."""

import pytest
from test_local_narrator import local_server, wait_for

from rpg_vkr.application import Session
from rpg_vkr.domain.character import Character
from rpg_vkr.narrative.cloud import CloudProfile
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.story import story_payload


@pytest.mark.parametrize("model", ["openrouter/free", "test/model:free"])
def test_free_router_and_fixed_free_model_cannot_fall_back_to_priced_provider(model):
    profile = CloudProfile("openrouter", model, "fake-test-key", free_only=True)
    payload = profile.payload(story_payload(build_frame(Session(seed=42)), model, "осмотрюсь"))
    assert payload["model"] == model
    assert payload["provider"] == {
        "max_price": {"prompt": 0, "completion": 0, "request": 0},
        "allow_fallbacks": False,
    }
    assert "options" not in payload and payload["stream"] is False
    assert "fake-test-key" not in repr(profile)


@pytest.mark.parametrize(
    "provider,model", [("openai", "test-model"), ("openrouter", "some/paid-model")]
)
def test_free_mode_rejects_paid_ids_instead_of_silently_changing_route(provider, model):
    with pytest.raises(ValueError, match="бесплатного"):
        CloudProfile(provider, model, "fake-test-key", free_only=True)


def test_paid_api_is_still_an_explicit_separate_profile():
    profile = CloudProfile("openrouter", "some/paid-model", "fake-test-key", free_only=False)
    assert "provider" not in profile.payload({"messages": []})


def configure(window, monkeypatch, url):
    import rpg_vkr.narrative.cloud as cloud

    monkeypatch.setitem(cloud.ENDPOINTS, "openrouter", url + "/chat/completions")
    window.ai_provider.setCurrentIndex(2)
    window.cloud_key.setText("fake-test-key")
    window.cloud_allowed.setChecked(True)
    window.enable_local_narrator.setChecked(True)


def test_free_cloud_ui_default_and_request_contains_price_guard(window, qt_app, monkeypatch):
    with local_server(mode="plain_cloud") as (url, requests):
        configure(window, monkeypatch, url)
        assert window.cloud_model.text() == "openrouter/free"
        assert window.cloud_free_only.isChecked()
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 1
        assert requests[0][1]["provider"]["max_price"]["completion"] == 0
        assert len(window._session.turns) == 1
        assert window._session.turns[0].scene.model == "test/free-model:free"
        assert window._session.narrations[0].model == "test/free-model:free"
        assert (
            "Фактическая модель API: test/free-model:free" in window.narrator_details.toPlainText()
        )
        assert "fake-test-key" not in window.narrator_details.toPlainText()
        assert "fake-test-key" not in str(window._session.to_dict())


def test_429_keeps_original_input_and_never_tries_a_paid_model(window, qt_app, monkeypatch):
    with local_server(mode="plain_cloud_quota") as (url, requests):
        configure(window, monkeypatch, url)
        before = window._session.to_dict(), window._session.dice.checkpoint()
        window.action_input.setText("спросить у жительницы, что она тут делает")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 1
        assert "429" in window.narrator_status.text()
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == "спросить у жительницы, что она тут делает"


def test_computed_attack_survives_cloud_quota_without_reexecution(window, qt_app, monkeypatch):
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window._session = Session.create_hero(Character(), "scout", seed=42)
    with local_server(mode="plain_cloud_quota") as (url, requests):
        configure(window, monkeypatch, url)
        window.action_input.setText("ударить стражника ножом")
        window.send_button.click()
        before = window._session.to_dict(), window._session.dice.checkpoint()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 1
        assert len(window._session.turns) == 1
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == ""
        assert "Промах" in window.journal.toPlainText()


def test_free_checkbox_prevents_paid_request_before_network(window):
    window.ai_provider.setCurrentIndex(2)
    window.cloud_allowed.setChecked(True)
    window.cloud_key.setText("fake-test-key")
    window.cloud_model.setText("some/paid-model")
    window.enable_local_narrator.setChecked(True)
    window.action_input.setText("осмотрюсь, где я")
    window.send_button.click()
    assert not window.ollama.busy and not window._session.turns
    assert window.action_input.text() == "осмотрюсь, где я"
    assert "бесплатного" in window.narrator_status.text()
