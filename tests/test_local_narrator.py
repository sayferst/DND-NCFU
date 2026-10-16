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
def local_server(*, mode="ok", delay=0):
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
            if delay and self.path == "/api/chat":
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
                if mode == "effects":
                    content["gold"] = 1000
                payload = json.dumps(
                    {"message": {"role": "assistant", "content": json.dumps(content)}}
                ).encode()
            self.send_response(500 if mode == "error" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
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


@pytest.mark.parametrize("mode", ["bad_json", "effects", "large", "error"])
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
        assert "ИИ-рассказчик · local-test:1" in window.journal.toPlainText()
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

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    window.ollama.base_url = f"http://127.0.0.1:{port}"
    window.find_models_button.click()
    wait_for(qt_app, lambda: not window.ollama.busy)
    assert "недоступна" in window.narrator_status.text()
    window._run_command("бросить кубик")
    assert window._session.turns[-1].roll.value == 4
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
