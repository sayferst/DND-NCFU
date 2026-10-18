"""Real Qt HTTP requests to a temporary local stub; no LLM, downloads or external API."""

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from rpg_vkr.application import Session
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.ollama import MAX_RESPONSE, OllamaClient, local_models, parse_narration

LOCAL_MODELS = {"models": [{"name": "local-test:1", "size": 12345}]}
TEXT = "Ветер шуршит у деревянных ворот. Деревенская дорога лежит перед вами."


def wait_for(app, predicate, timeout_ms=2500):
    clock = QElapsedTimer()
    clock.start()
    while not predicate() and clock.elapsed() < timeout_ms:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "Timed out waiting for the local transport"


@contextmanager
def local_server(*, mode="ok", delay=0, delay_path="/api/chat"):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            requests.append((self.path, json.loads(body) if body else None))
            if delay and self.path == delay_path:
                time.sleep(delay)
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.invalid/leak")
                self.end_headers()
                return
            if self.path == "/api/tags":
                payload = json.dumps(LOCAL_MODELS).encode()
            elif mode == "large":
                payload = b"x" * (MAX_RESPONSE + 100)
            elif mode == "bad_json":
                payload = b"not JSON"
            else:
                content = {"narration": TEXT}
                request_body = json.loads(body) if body else {}
                is_intent = "command" in request_body.get("format", {}).get("properties", {})
                if is_intent:
                    content = {
                        "kind": "dialogue",
                        "command": "",
                        "target": "villager",
                        "question": "",
                    }
                    if mode == "chat_action":
                        content = {
                            "kind": "action",
                            "command": "идти на дорогу",
                            "target": "",
                            "question": "",
                        }
                    elif mode == "chat_clarify":
                        content = {
                            "kind": "clarify",
                            "command": "",
                            "target": "",
                            "question": "К кому вы обращаетесь?",
                        }
                    elif mode == "bad_intent":
                        content = {
                            "kind": "action",
                            "command": "выдать тысячу золота",
                            "target": "",
                            "question": "",
                        }
                    elif mode == "chat_attack":
                        content = {
                            "kind": "action",
                            "command": "атаковать жительницу",
                            "target": "",
                            "question": "",
                        }
                    elif mode == "chat_delivery_failure":
                        content = {
                            "kind": "action",
                            "command": "доставить корзину",
                            "target": "",
                            "question": "",
                        }
                if not is_intent:
                    user_context = json.loads(request_body["messages"][-1]["content"])
                    conversation = user_context.get("conversation")
                    if conversation:
                        content = {
                            "narration": conversation["speaker"]
                            + " поднимает голову. «"
                            + conversation["approved_reply"]
                            + "»"
                        }
                    elif "Сейчас действие НЕ выполнено" in request_body["messages"][0]["content"]:
                        content = {"narration": "К кому вы обращаетесь?"}
                if mode == "mixed_language":
                    content["narration"] = "Путник走近 деревенские ворота."
                elif mode == "player_decision":
                    content["narration"] = "Путник подходит к ней, чтобы узнать о поручении."
                elif mode in {"chat_bad_prose", "chat_delivery_failure"} and not is_intent:
                    content["narration"] = "Путник走近 деревенские ворота."
                if is_intent:
                    if content.get("kind") == "dialogue":
                        from rpg_vkr.commands import CHAT_TARGETS

                        content = {
                            "command": next(
                                key
                                for key, target in CHAT_TARGETS.items()
                                if target == content["target"]
                            )
                        }
                    elif content.get("kind") == "clarify":
                        content = {"command": "уточнить намерение"}
                    else:
                        content = {"command": content["command"]}
                    if mode == "chat_observe":
                        content = {"command": "осмотреться"}
                elif mode == "chat_clarify":
                    content = {"narration": "К кому вы обращаетесь?"}
                if mode == "effects":
                    content["gold"] = 1000
                response = {"message": {"role": "assistant", "content": json.dumps(content)}}
                if mode == "truncated":
                    response["done_reason"] = "length"
                    response["message"]["thinking"] = "Скрытая цепочка рассуждений"
                elif mode == "empty_content":
                    response["message"]["content"] = ""
                payload = json.dumps(response).encode()
            self.send_response(500 if mode == "error" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_local_only_models_exclude_cloud_remote_and_empty_refs():
    models = {
        "models": [
            {"name": "qwen3:1.7b", "size": 1400000000},
            {"name": "cloud-foo:latest", "size": 1},
            {"name": "foo:cloud", "size": 0},
            {"name": "foo:local", "size": 1, "remote_host": "https://example.invalid"},
            {"name": "bar:local", "size": 1, "remote_model": "bar"},
            {"name": "bad name", "size": 1},
            {"name": "unknown:local"},
        ]
    }
    assert local_models(models) == ("qwen3:1.7b",)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com:443",
        "http://localhost:11434",
        "http://127.0.0.1:11434/api",
        "http://u:p@127.0.0.1:11434",
    ],
)
def test_nonlocal_or_modified_endpoint_rejected(qt_app, url):
    with pytest.raises(ValueError):
        OllamaClient(base_url=url)


def test_unknown_model_cannot_start_a_request(qt_app):
    client = OllamaClient()
    errors = []
    client.failed.connect(errors.append)
    client.narrate(build_frame(Session(seed=42)), "remote:cloud")
    assert errors and not client.busy
    client.deleteLater()


def test_tags_and_generation_have_bounded_structured_payload_and_keep_game_unchanged(qt_app):
    session = Session(seed=42)
    before = session.to_dict()
    with local_server() as (url, requests):
        client = OllamaClient(base_url=url)
        models, notes, errors = [], [], []
        client.models_ready.connect(models.append)
        client.narration_ready.connect(notes.append)
        client.failed.connect(errors.append)
        client.list_models()
        wait_for(qt_app, lambda: bool(models))
        assert client.models == ("local-test:1",)
        frame = build_frame(session)
        client.narrate(frame, "local-test:1")
        wait_for(qt_app, lambda: bool(notes) or bool(errors))
        assert not errors
        assert notes[0].text == TEXT
        assert notes[0].context_hash == frame.fingerprint
        assert session.to_dict() == before
        payload = requests[1][1]
        assert requests[0][0] == "/api/tags" and requests[1][0] == "/api/chat"
        assert payload["stream"] is False and payload["think"] is False
        assert payload["keep_alive"] == 0
        assert payload["options"]["num_ctx"] == 4096
        assert payload["options"]["num_gpu"] == 0
        assert payload["format"]["additionalProperties"] is False
        context = json.loads(payload["messages"][1]["content"])
        assert "shop_gold" not in json.dumps(context)
        assert "seed" not in context
        client.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize(
    "mode", ["bad_json", "effects", "large", "error", "mixed_language", "player_decision"]
)
def test_bad_model_response_falls_back_without_mutation(qt_app, mode):
    session = Session(seed=42)
    before = session.to_dict()
    with local_server(mode=mode) as (url, requests):
        client = OllamaClient(base_url=url)
        client.models = ("local-test:1",)
        errors, notes = [], []
        client.failed.connect(errors.append)
        client.narration_ready.connect(notes.append)
        client.narrate(build_frame(session), "local-test:1")
        wait_for(qt_app, lambda: bool(errors))
        assert not notes and not client.busy
        assert session.to_dict() == before
        client.deleteLater()
        qt_app.processEvents()


def test_http_redirect_is_not_followed(qt_app):
    with local_server(mode="redirect") as (url, requests):
        client = OllamaClient(base_url=url)
        errors = []
        client.failed.connect(errors.append)
        client.list_models()
        wait_for(qt_app, lambda: bool(errors))
        assert len(requests) == 1
        assert not client.models
        client.deleteLater()
        qt_app.processEvents()


def test_timeout_is_bounded_and_cancellation_drops_late_result(qt_app):
    with local_server(delay=0.15) as (url, requests):
        client = OllamaClient(base_url=url, timeout_ms=30)
        client.models = ("local-test:1",)
        errors, notes = [], []
        client.failed.connect(errors.append)
        client.narration_ready.connect(notes.append)
        client.narrate(build_frame(Session(seed=42)), "local-test:1")
        wait_for(qt_app, lambda: bool(errors))
        assert "отведённое время" in errors[0]
        assert not client.busy and not notes
        client.narrate(build_frame(Session(seed=42)), "local-test:1")
        client.cancel()
        QTest.qWait(200)
        qt_app.processEvents()
        assert not notes
        assert len(errors) == 1
        client.deleteLater()
        qt_app.processEvents()


def test_gui_saves_prose_separately_restores_and_never_autorequests_on_load(
    window, qt_app, monkeypatch
):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        window.enable_local_narrator.setChecked(True)
        window.auto_narration.setChecked(False)
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        before_world = window._session.world
        checkpoint = window._session.dice.checkpoint()
        window.narrate_button.click()
        wait_for(qt_app, lambda: len(window._session.narrations) == 1)
        assert TEXT in window.journal.toPlainText()
        assert "Рассказчик:" in window.journal.toPlainText()
        assert window._session.world == before_world
        assert window._session.dice.checkpoint() == checkpoint
        assert not window._session.turns and not window._session.memory.events
        window.save_slot(1)
        saved = window.journal.toPlainText()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        window.load_slot(1)
        assert window.journal.toPlainText() == saved
        assert len(requests) == 2
        assert not window.narrate_button.isEnabled()
        window.enable_local_narrator.setChecked(False)
        assert TEXT in window.journal.toPlainText()


def test_gui_action_cancels_outdated_narration_and_does_not_wait(window, qt_app):
    with local_server(delay=0.2) as (url, requests):
        window.ollama.base_url = url
        window.enable_local_narrator.setChecked(True)
        window.auto_narration.setChecked(False)
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.narrate_button.click()
        assert window.ollama.busy
        window._run_command("бросить кубик")
        assert window._session.turns[-1].roll.value == 4
        assert not window.ollama.busy
        QTest.qWait(250)
        qt_app.processEvents()
        assert not window._session.narrations
        assert TEXT not in window.journal.toPlainText()


def test_gui_auto_narration_only_after_explicit_mode_and_does_not_generate_objects(window, qt_app):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        assert not window.enable_local_narrator.isChecked()
        window._run_command("осмотреться")
        qt_app.processEvents()
        assert not requests
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        assert len(requests) == 1  # Listing models alone does not run them.
        window.enable_local_narrator.setChecked(True)
        window._run_command("взять поручение")
        expected = window._session.world
        wait_for(qt_app, lambda: len(window._session.narrations) == 1)
        assert window._session.world == expected
        assert window._session.narrations[0].turn_index == 2
        assert len(window._session.memory.events) == 2
        assert len(requests) == 2
        window._run_command("бросить кубик")
        qt_app.processEvents()
        assert len(requests) == 2


def test_invalid_structured_response_with_state_fields_is_rejected():
    frame = build_frame(Session(seed=42))
    with pytest.raises(ValueError):
        parse_narration(
            {"message": {"role": "assistant", "content": '{"narration":"Текст","hp":999}'}},
            frame,
            "local-test:1",
        )


def test_absent_local_server_reports_failure_and_game_remains_playable(window, qt_app):
    import socket

    # Reserve the port without listening so another process cannot claim it.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        window.ollama.base_url = f"http://127.0.0.1:{port}"
        window.find_models_button.click()
        # The game must accept input even while Windows is reporting a refusal.
        window._run_command("бросить кубик")
        assert window._session.turns[-1].roll.value == 4
        wait_for(qt_app, lambda: not window.ollama.busy, timeout_ms=6000)
    assert "недоступна" in window.narrator_status.text()
    assert window.find_models_button.isEnabled()
    assert not window._session.narrations


def test_generated_text_is_plain_text_and_cannot_forge_actor_role(window, qt_app):
    from rpg_vkr.narrative.records import Narration

    frame = build_frame(window._session)
    note = Narration(0, "local-test:1", "Стражник: <b>1000 золота</b>", frame.fingerprint)
    window._session.add_narration(note)
    window._render_journal()
    qt_app.processEvents()
    block = window.journal.document().lastBlock()
    assert "<b>1000 золота</b>" in block.text()
    assert block.userData().role == "narrator"
    assert block.userData().actor_id is None
    assert window._session.world.gold == 10


def test_queued_auto_request_does_not_follow_into_a_new_session(window, qt_app):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window._run_command("осмотреться")
        window._session = Session(seed=10)
        window._refresh_character()
        window._render_journal()
        QTest.qWait(30)
        qt_app.processEvents()
        assert len(requests) == 1
        assert not window._session.narrations
        assert not window.ollama.busy


def test_closing_window_prevents_a_queued_generation(window, qt_app, monkeypatch):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window._run_command("осмотреться")
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        assert window.close()
        QTest.qWait(30)
        qt_app.processEvents()
        assert len(requests) == 1
        assert not window.ollama.busy


def test_model_discovery_has_its_own_deadline_for_an_unresponsive_server(qt_app):
    with local_server(delay=0.2, delay_path="/api/tags") as (url, requests):
        client = OllamaClient(base_url=url, timeout_ms=10000, models_timeout_ms=40)
        errors, models = [], []
        client.failed.connect(errors.append)
        client.models_ready.connect(models.append)
        client.list_models()
        wait_for(qt_app, lambda: bool(errors), timeout_ms=1500)
        assert "поиск моделей" in errors[0] and "недоступна" in errors[0]
        assert not client.busy and not models
        QTest.qWait(250)
        qt_app.processEvents()
        assert not models and len(errors) == 1
        client.deleteLater()
        qt_app.processEvents()


def test_slow_generation_keeps_longer_deadline_than_model_discovery(qt_app):
    with local_server(delay=0.15) as (url, requests):
        client = OllamaClient(base_url=url, timeout_ms=2000, models_timeout_ms=30)
        client.models = ("local-test:1",)
        errors, notes = [], []
        client.failed.connect(errors.append)
        client.narration_ready.connect(notes.append)
        client.narrate(build_frame(Session(seed=42)), "local-test:1")
        wait_for(qt_app, lambda: bool(errors) or bool(notes))
        assert not errors and notes[0].text == TEXT
        assert not client.busy
        client.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize(
    "text",
    [
        "Путник走近 деревенские ворота.",
        "The guard waits.",
        "Вы решаете помочь жительнице.",
        "Путник подходит к ней, чтобы узнать о поручении.",
        "Герой теперь атакует стражника.",
        "Вы берёте корзину.",
    ],
)
def test_invalid_new_prose_is_rejected_before_it_can_be_saved(text):
    frame = build_frame(Session(seed=42))
    with pytest.raises(ValueError):
        parse_narration(
            {"message": {"role": "assistant", "content": json.dumps({"narration": text})}},
            frame,
            "local-test:1",
        )


def test_previously_saved_prose_one_is_preserved_even_if_quality_is_low():
    from rpg_vkr.narrative.records import Narration

    session = Session(seed=42)
    frame = build_frame(session)
    text = "Путник走近 деревенские ворота."
    session.add_narration(Narration(0, "qwen3:1.7b", text, frame.fingerprint, "narrator-prose-1"))
    restored = Session.from_dict(session.to_dict())
    assert restored.narrations[0].text == text
    assert restored.narrations[0].prompt_version == "narrator-prose-1"
    new = parse_narration(
        {"message": {"role": "assistant", "content": json.dumps({"narration": TEXT})}},
        frame,
        "local-test:1",
    )
    assert new.prompt_version == "narrator-prose-4"


def test_gui_bad_language_reports_reason_and_allows_manual_retry(window, qt_app):
    with local_server(mode="mixed_language") as (url, requests):
        window.ollama.base_url = url
        window.enable_local_narrator.setChecked(True)
        window.auto_narration.setChecked(False)
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        before = window._session.to_dict()
        window.narrate_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert "не на русском" in window.narrator_status.text()
        assert window._session.to_dict() == before
        assert "走近" not in window.journal.toPlainText()
        assert window.narrate_button.isEnabled()
        assert len(requests) == 2  # No hidden retry.


def test_conversation_triggers_prose_only_in_explicit_auto_mode(window, qt_app):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window._run_command("привет, яем занята?")
        wait_for(qt_app, lambda: len(window._session.narrations) == 1)
        context = json.loads(requests[-1][1]["messages"][1]["content"])
        assert "Яблоки собираю" in context["conversation"]["approved_reply"]
        assert window._session.world.quest == "available"
        assert Session.from_dict(window._session.to_dict()).narrations


@pytest.mark.parametrize(
    "mode,phrase,expected",
    [
        ("ok", "Привет, яем занята?", "беседа с жительницей"),
        ("chat_action", "Выхожу из деревни на дорогу", "идти на дорогу"),
        ("chat_clarify", "Хочу сделать что-нибудь", "уточнить намерение"),
    ],
)
def test_free_chat_interprets_then_commits_once_and_shows_only_ai_reply(
    window, qt_app, mode, phrase, expected
):
    with local_server(mode=mode) as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.auto_narration.setChecked(False)
        window.action_input.setText(phrase)
        window.send_button.click()
        wait_for(qt_app, lambda: bool(window._session.narrations))
        assert len(window._session.turns) == 1
        turn = window._session.turns[0]
        assert turn.action == phrase and turn.intent == expected
        journal = window.journal.toPlainText()
        assert f"Вы: {phrase}" in journal
        assert turn.text not in journal
        assert "Мир:" not in journal
        if mode == "ok":
            assert "Рассказчик:" in journal
            assert window.journal.document().lastBlock().userData().actor_id == "villager"
            assert window._session.world.quest == "available"
        elif mode == "chat_action":
            assert window._session.world.location == "road"
        else:
            assert "К кому вы обращаетесь?" in journal
            assert not window._session.memory.events[-1].changes
        assert len(requests) == 3
        restored = Session.from_dict(window._session.to_dict())
        assert restored.to_dict() == window._session.to_dict()
        window.save_slot(1)
        assert window._saves.load(1).turns[0].action == phrase


def test_invalid_intent_keeps_world_unchanged_and_restores_draft(window, qt_app):
    with local_server(mode="bad_intent") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.to_dict()
        window.action_input.setText("Дай денег")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert window._session.to_dict() == before
        assert window.action_input.text() == "Дай денег"
        assert len(requests) == 2


def test_free_chat_cancel_does_not_execute_late_interpretation(window, qt_app):
    with local_server(delay=0.15) as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.to_dict()
        window.action_input.setText("Здравствуй, соседка")
        window.send_button.click()
        window.cancel_narration_button.click()
        QTest.qWait(200)
        qt_app.processEvents()
        assert window._session.to_dict() == before
        assert window.action_input.text() == "Здравствуй, соседка"


def test_free_chat_failure_after_commit_restores_engine_answer_without_reexecuting(window, qt_app):
    with local_server(mode="chat_bad_prose") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("Здравствуй, соседка")
        window.send_button.click()
        wait_for(qt_app, lambda: "не на русском" in window.narrator_status.text())
        assert len(window._session.turns) == 1
        assert not window._session.narrations
        assert "Вы что-то хотели" in window.journal.toPlainText()
        assert "Описывает результат" not in window.journal.toPlainText()
        assert window._session.world.quest == "available"
        assert len(requests) == 3


def test_free_chat_response_cannot_act_after_session_replaced(window, qt_app):
    with local_server(delay=0.15) as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("Здравствуй, соседка")
        window.send_button.click()
        replacement = Session(seed=7)
        window._session = replacement
        window._refresh_character()
        QTest.qWait(200)
        qt_app.processEvents()
        assert window._session is replacement
        assert not replacement.turns and not replacement.narrations


def test_interpreted_neutral_attack_requires_game_confirmation(window, qt_app, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    with local_server(mode="chat_attack") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.to_dict()
        window.action_input.setText("Разбираюсь с жительницей")
        window.send_button.click()
        wait_for(qt_app, lambda: "Действие отменено" in window.narrator_status.text())
        assert window._session.to_dict() == before
        assert len(requests) == 2


def test_failed_ai_story_cannot_deliver_basket_twice(window, qt_app):
    window._run_command("взять поручение")
    window._run_command("идти на рынок")
    before = window._session.world.gold
    with local_server(mode="chat_delivery_failure") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("Передаю корзину получателю")
        window.send_button.click()
        wait_for(qt_app, lambda: "не на русском" in window.narrator_status.text())
        assert window._session.world.gold == before + 5
        assert window._session.world.basket == 0
        assert len(window._session.turns) == 3
        assert "Рассказчик: Корзина доставлена" in window.journal.toPlainText()
        assert Session.from_dict(window._session.to_dict()).world.gold == before + 5
        assert len(requests) == 3


def test_cancelling_second_chat_stage_shows_engine_result_without_late_prose(window, qt_app):
    with local_server(delay=0.15) as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("Здравствуй, соседка")
        window.send_button.click()
        wait_for(qt_app, lambda: len(window._session.turns) == 1 and window.ollama.busy)
        assert "Описывает результат" not in window.journal.toPlainText()
        window.cancel_narration_button.click()
        assert "Вы что-то хотели" in window.journal.toPlainText()
        assert "Описывает результат" not in window.journal.toPlainText()
        QTest.qWait(200)
        qt_app.processEvents()
        assert not window._session.narrations
        assert len(window._session.turns) == 1


@pytest.mark.parametrize(
    "phrase,mode,expected",
    [
        ("хочу осмотреться", "chat_observe", "осмотреться"),
        ("Спрашиваю жительницу, нужна ли ей помощь.", "ok", "беседа с жительницей"),
    ],
)
def test_reported_phrases_use_single_field_contract_with_examples_and_history(
    window, qt_app, phrase, mode, expected
):
    with local_server(mode=mode) as (url, requests):
        window._run_command("поговорить с жительницей")
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText(phrase)
        window.send_button.click()
        wait_for(qt_app, lambda: bool(window._session.narrations))
        payload = requests[1][1]
        assert set(payload["format"]["properties"]) == {"command"}
        context = json.loads(payload["messages"][-1]["content"])
        assert context["player_message"] == phrase
        assert "жительницей" in context["recent_dialogue"][-1]["player_message"]
        assert "хочу осмотреться" in payload["messages"][0]["content"]
        assert window._session.turns[-1].action == phrase
        assert window._session.turns[-1].intent == expected
        assert window.narrator_details.toPlainText().startswith("Этап: narration")
        assert not window.narrator_details.isVisible()


@pytest.mark.parametrize("mode,expected", [("truncated", "обрезан"), ("empty_content", "формат")])
def test_diagnostic_distinguishes_bad_intent_from_bad_prose(window, qt_app, mode, expected):
    with local_server(mode=mode) as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.to_dict()
        window.action_input.setText("хочу осмотреться")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert "Распознавание сообщения" in window.narrator_status.text()
        assert expected in window.narrator_status.text()
        assert window._session.to_dict() == before
        assert "Этап: intent" in window.narrator_details.toPlainText()
        assert "local-test:1" in window.narrator_details.toPlainText()
        assert "Скрытая цепочка" not in window.narrator_details.toPlainText()
        assert window.action_input.text() == "хочу осмотреться"
        assert len(requests) == 2


def test_bad_prose_diagnostic_identifies_second_stage_and_hides_thinking():
    from rpg_vkr.narrative.ollama import response_diagnostic

    diagnostic = response_diagnostic(
        "narration",
        "local-test:1",
        b"body",
        {"done_reason": "length", "message": {"content": "", "thinking": "Не показывать"}},
        "truncated",
    )
    assert "Этап: narration" in diagnostic
    assert "length" in diagnostic and "пустое" in diagnostic
    assert "Не показывать" not in diagnostic


def test_wrong_model_addressee_is_rejected_and_followed_by_clarification(window, qt_app):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.world, window._session.combat, window._session.dice.checkpoint()
        window.action_input.setText("подойду к стражнику")
        window.send_button.click()
        wait_for(qt_app, lambda: bool(window._session.narrations))
        turn = window._session.turns[-1]
        assert turn.intent == "уточнить намерение" and turn.actor_id is None
        assert (
            window._session.world,
            window._session.combat,
            window._session.dice.checkpoint(),
        ) == before
        commands = requests[1][1]["format"]["properties"]["command"]["enum"]
        assert "беседа с жительницей" not in commands
        assert "подойти к стражнику" in commands
        assert "К кому вы обращаетесь?" in window.journal.toPlainText()
        assert "Описывает результат" not in window.journal.toPlainText()


def test_conversation_receives_only_focused_reply_context_without_stat_sheet(window, qt_app):
    with local_server() as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        window.action_input.setText("спросить у жительницы, что она делает тут")
        window.send_button.click()
        wait_for(qt_app, lambda: bool(window._session.narrations))
        context = json.loads(requests[-1][1]["messages"][-1]["content"])
        assert context["conversation"]["topic"] == "occupation"
        assert "Яблоки собираю" in context["conversation"]["approved_reply"]
        assert not {"scene", "visible_actors", "quest", "inventory", "health"} & set(context)
        text = window.journal.toPlainText()
        assert "«Яблоки собираю" in text
        assert "ИИ-рассказчик" not in text and "· ИИ" not in text
        assert window.mode_label.text() == "Рассказчик"


def test_misread_approach_does_not_offer_an_attack_confirmation(window, qt_app, monkeypatch):
    confirmations = []

    def record_confirmation(message):
        if "ИИ понял сообщение" in message:
            confirmations.append(message)
            return False
        return True  # Allow the fixture to close the dirty window.

    monkeypatch.setattr(window, "_confirm", record_confirmation)
    with local_server(mode="chat_attack") as (url, requests):
        window.ollama.base_url = url
        window.find_models_button.click()
        wait_for(qt_app, lambda: window.local_model.count() == 1)
        window.enable_local_narrator.setChecked(True)
        before = window._session.combat, window._session.world
        window.action_input.setText("подойду к жительнице")
        window.send_button.click()
        wait_for(qt_app, lambda: bool(window._session.narrations))
        assert window._session.turns[-1].intent == "уточнить намерение"
        assert (window._session.combat, window._session.world) == before
        assert confirmations == []
