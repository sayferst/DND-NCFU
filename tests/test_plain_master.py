"""Actual Qt HTTP with plain prose/repair, automatic API adapter and chat-only UI."""

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton
from test_local_narrator import local_server, wait_for

from rpg_vkr.application import Session
from rpg_vkr.domain.campaign import Campaign
from rpg_vkr.domain.character import Character
from rpg_vkr.narrative.cloud import CloudProfile, normalize_completion
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.story import mechanical_request, story_payload, story_proposal, story_text
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow


@pytest.mark.parametrize(
    "mode,calls",
    [
        ("plain_ok", 1),
        ("plain_empty_first", 2),
        ("plain_mixed_first", 2),
        ("plain_truncated_first", 2),
    ],
)
def test_real_http_prose_and_single_repair_after_hero_creation(window, qt_app, mode, calls):
    window._session = Session(
        seed=42,
        character=Character(name="Асуна"),
        campaign=Campaign.create("Асуна выросла у моря и ищет брата."),
    )
    window._refresh_character()
    window.director_mode.setChecked(True)
    with local_server(mode=mode) as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.world, window._session.dice.checkpoint()
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(window._session.turns) == 1
        assert len(requests) == 1 + calls
        assert window._session.turns[0].scene.version == "scene-director-4"
        assert (window._session.world, window._session.dice.checkpoint()) == before
        for _, body in requests[1:]:
            assert "format" not in body
            assert body["keep_alive"] == "5m" and body.get("think", False) is False
        assert "Асуна выросла у моря" in requests[1][1]["messages"][-1]["content"]
        assert "Попытка 2" in window.narrator_details.toPlainText() if calls == 2 else True
        assert "продать бинт" not in window._session.turns[0].action


def test_two_bad_attempts_restore_input_without_side_effects(window, qt_app):
    window.director_mode.setChecked(True)
    with local_server(mode="plain_always_bad") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.to_dict()
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 3
        assert window._session.to_dict() == before
        assert window.action_input.text() == "осмотрюсь, где я"
        assert "двух попыток" in window.narrator_status.text()


def test_compound_question_needs_spoken_answer():
    frame = build_frame(Session(seed=42))
    data = {
        "message": {"role": "assistant", "content": "Жительница стоит у ворот и собирает яблоки."}
    }
    with pytest.raises(ValueError, match="прямо ответить"):
        story_proposal(data, frame, "подойду к девушке и спрошу, как дела")


def test_user_supplied_bad_transaction_is_never_extracted():
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/validation/windows-director-mixed-response-2026-10-19.json"
    )
    bad = json.loads(path.read_text(encoding="utf-8"))["response"]
    with pytest.raises(ValueError, match="команду вместо рассказа"):
        story_text({"message": {"role": "assistant", "content": json.dumps(bad)}})
    assert mechanical_request("осмотрюсь, где я") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("хочу атаковать волка", "атаковать волка"),
        ("продать бинт", "продать бинт"),
        ("могу ли продать бинт?", None),
        ("не хочу продать бинт", None),
        ("подойду к девушке и спрошу, как дела", None),
        ("осмотреться с интеллектом и выносливостью", "исследовать окрестности"),
    ],
)
def test_mechanics_require_explicit_player_evidence(text, expected):
    assert mechanical_request(text) == expected


def test_no_manual_mode_or_game_action_buttons_in_live_ui(qt_app, tmp_path):
    window = MainWindow(session=Session(seed=42), saves=SaveSlots(tmp_path / "saves"))
    window.show()
    qt_app.processEvents()
    assert not hasattr(window, "manual_chatgpt")
    assert not window.quick_controls.isVisible()
    assert not window.narrate_button.isVisible()
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        qt_app.processEvents()
        assert all(
            not b.isVisible() for b in window.findChildren(QPushButton) if b.property("game_action")
        )
    window.resize(1500, 900)
    window._refresh_character()
    assert not window.quick_controls.isVisible()
    assert all(b.isEnabled() for b in window.save_buttons.values())
    window.close()
    window.deleteLater()


def test_cloud_is_opt_in_and_has_no_subscription_login(window, qt_app):
    window.ai_provider.setCurrentIndex(1)
    window.cloud_model.setText("test-model")
    window.cloud_key.setText("fake-test-key")
    window.enable_local_narrator.setChecked(True)
    window.action_input.setText("осмотрюсь, где я")
    window.send_button.click()
    assert not window.ollama.busy
    assert not window._session.turns
    assert "разрешите" in window.narrator_status.text()


def test_automatic_cloud_exchange_over_transport_without_key_in_logs(window, qt_app, monkeypatch):
    import rpg_vkr.narrative.cloud as cloud

    with local_server(mode="plain_cloud") as (url, requests):
        monkeypatch.setitem(cloud.ENDPOINTS, "openai", url + "/chat/completions")
        window.ai_provider.setCurrentIndex(1)
        window.cloud_model.setText("test-model")
        window.cloud_key.setText("fake-test-key")
        window.cloud_allowed.setChecked(True)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(window._session.turns) == 1
        assert len(requests) == 1
        assert requests[0][0] == "/chat/completions"
        assert requests[0][1]["_test_auth_ok"]
        assert "options" not in requests[0][1] and "format" not in requests[0][1]
        assert "fake-test-key" not in window.ollama.last_diagnostic
        assert "fake-test-key" not in repr(window.ollama.cloud)


def test_cloud_uses_https_and_omits_local_options():
    profile = CloudProfile("openai", "gpt-4.1-mini", "fake-test-key")
    assert profile.endpoint.startswith("https://")
    payload = profile.payload(story_payload(build_frame(Session(seed=42)), "x", "где я"))
    assert set(payload) == {"model", "messages", "stream", "max_completion_tokens", "temperature"}
    with pytest.raises(ValueError):
        CloudProfile("http://somewhere.invalid", "x", "fake-test-key")
    assert (
        normalize_completion(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Текст"}, "finish_reason": "stop"}
                ]
            }
        )["message"]["content"]
        == "Текст"
    )


def test_confirmed_prose_does_not_repeat_mechanical_action(window, qt_app):
    window.director_mode.setChecked(True)
    with local_server(mode="plain_ok") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("бросить кубик")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(window._session.turns) == 1
        assert window._session.turns[0].roll.value == 4
        assert len(window._session.narrations) == 1
        assert window._session.submit("бросить кубик").roll.value == 1


def test_previous_manual_save_still_loads_without_manual_feature():
    path = Path(__file__).parent / "fixtures" / "save-v12.json"
    original = path.read_bytes()
    data = json.loads(original)
    session = Session.from_dict(data["session"], version=12)
    assert session.turns[0].scene.version == "scene-director-1"
    assert session.turns[0].scene.model == "chatgpt-manual"
    assert session.narrations[0].prompt_version == "narrator-prose-7"
    assert session.submit("бросить кубик").roll.value == 4
    assert path.read_bytes() == original


def test_real_probe_script_with_synthetic_http_does_not_touch_saves(tmp_path):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    with local_server(mode="plain_probe") as (url, requests):
        result = subprocess.run(
            [
                sys.executable,
                str(root / "scripts/check_narrator.py"),
                "--model",
                "local-test:1",
                "--base-url",
                url,
                "--report-dir",
                str(tmp_path / "diagnostics"),
            ],
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        reports = list((tmp_path / "diagnostics").glob("*.json"))
        assert len(reports) == 1
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report["protocol_passed"]
        assert len(report["cases"]) == 5 and all(c["accepted"] for c in report["cases"])
        assert len([r for r in requests if r[0] == "/api/chat"]) == 4
        assert not (tmp_path / "saves").exists()


def test_cloud_redirect_is_not_followed_with_authorization(window, qt_app, monkeypatch):
    import rpg_vkr.narrative.cloud as cloud

    with local_server(mode="redirect") as (url, requests):
        monkeypatch.setitem(cloud.ENDPOINTS, "openai", url + "/chat/completions")
        window.ai_provider.setCurrentIndex(1)
        window.cloud_model.setText("test-model")
        window.cloud_key.setText("fake-test-key")
        window.cloud_allowed.setChecked(True)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(requests) == 1
        assert not window._session.turns
        assert window.action_input.text() == "осмотрюсь, где я"
        assert "fake-test-key" not in window.ollama.last_diagnostic


@pytest.mark.parametrize("question", ["мастер, как выглядит девушка?", "как выглядит девушка?"])
def test_master_description_is_not_forced_into_npc_dialogue(question):
    data = {
        "message": {
            "role": "assistant",
            "content": (
                "У девушки тёмные волосы, убранные под платок. На рукавах следы яблочного сока."
            ),
        }
    }
    result = story_proposal(data, build_frame(Session(seed=42)), question)
    assert not result.focus_id
    payload = story_payload(build_frame(Session(seed=42)), "local-test:1", question)
    assert "вопрос ведущему" in payload["messages"][-1]["content"]


@pytest.mark.parametrize(
    "text",
    [
        'Жительница придерживает корзину. "Спасибо, держусь. Яблоки рассыпались".',
        "Жительница: Спасибо, держусь. Яблоки рассыпались, а мне ещё на рынок успеть.",
    ],
)
def test_ordinary_speech_typography_is_accepted_without_json_contract(text):
    data = {"message": {"role": "assistant", "content": text}}
    result = story_proposal(
        data, build_frame(Session(seed=42)), "подойду к девушке и спрошу, как дела"
    )
    assert result.focus_id == "villager"
    assert "«" in result.narration
