"""RouterAI contract from supplied docs; synthetic HTTP, never a paid/live request."""

import json
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtTest import QTest
from test_local_narrator import wait_for

from rpg_vkr.application import Session
from rpg_vkr.domain.character import Character
from rpg_vkr.narrative.cloud import CloudProfile
from rpg_vkr.narrative.routerai import parse_allowance, parse_models
from rpg_vkr.ui.narrator_panel import prepare_model

MODEL = "deepseek/deepseek-v4-pro-0813"
QUOTE = {
    "id": MODEL,
    "architecture": {"output_modalities": ["text"]},
    "pricing": {"prompt": "0.00030631848", "completion": "0.0015315924"},
    "pricing_units": {"prompt": "token", "completion": "token"},
    "supported_parameters": ["max_tokens", "temperature"],
}
ALLOWANCE = {
    "disabled": False,
    "limit": "2000.00",
    "usage_monthly": "100.00",
    "limit_remaining": "1900.00",
    "limit_reset": "monthly",
}


@contextmanager
def router_server(
    *,
    keys=None,
    key_status=200,
    chat_status=200,
    delay_key=0,
    bad_first=False,
    redirect=False,
    suggestion=None,
    world_plans=None,
    writer_text=None,
):
    records = []
    keys = [ALLOWANCE] if keys is None else keys

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else None
            records.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "authenticated": self.headers.get("Authorization")
                    == "Bearer routerai-test-key",
                    "has_auth": self.headers.get("Authorization") is not None,
                }
            )
            if redirect:
                self.send_response(302)
                self.send_header("Location", "https://example.invalid/never-follow")
                self.end_headers()
                return
            status = 200
            if self.path == "/api/v1/models":
                result = [{"data": [QUOTE]}]
            elif self.path == "/api/v1/key":
                if delay_key:
                    time.sleep(delay_key)
                count = sum(row["path"] == self.path for row in records)
                result = {"data": keys[min(count - 1, len(keys) - 1)]}
                status = key_status
            elif self.path == "/api/v1/chat/completions":
                count = sum(row["path"] == self.path for row in records)
                text = (
                    "走近"
                    if bad_first and count == 1
                    else "У ворот скрипят деревянные створки. Стражник смотрит на дорогу, "
                    "женщина придерживает корзину с яблоками."
                )
                if (
                    suggestion is not None
                    and "Режим: предложить категорию" in body["messages"][0]["content"]
                ):
                    text = json.dumps(suggestion, ensure_ascii=False)
                if world_plans is not None:
                    if "Режим: план изменений мира" in body["messages"][0]["content"]:
                        request = json.loads(body["messages"][1]["content"])
                        text = json.dumps(
                            world_plans.get(
                                request["player_message"],
                                {
                                    "steps": [],
                                    "places": [],
                                    "check": "none",
                                },
                            ),
                            ensure_ascii=False,
                        )
                    elif writer_text:
                        text = writer_text
                result = {
                    "model": MODEL,
                    "choices": [
                        {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                    ],
                    "usage": {"input_tokens": 320, "output_tokens": 75, "total_tokens": 395},
                }
                status = chat_status
            else:
                status, result = 404, {}
            if status != 200:
                result = {"error": "Never display server echo: routerai-test-key"}
            raw = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def configure(window, monkeypatch, url):
    import rpg_vkr.narrative.cloud as cloud
    import rpg_vkr.narrative.routerai as routerai

    monkeypatch.setitem(cloud.ENDPOINTS, "routerai", url + "/api/v1/chat/completions")
    monkeypatch.setattr(routerai, "CATALOG_URL", url + "/api/v1/models")
    monkeypatch.setattr(routerai, "KEY_URL", url + "/api/v1/key")
    window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
    window.cloud_model.setText(MODEL)
    window.cloud_key.setText("routerai-test-key")
    window.cloud_allowed.setChecked(True)
    window.enable_local_narrator.setChecked(True)


@pytest.mark.parametrize("data", [[QUOTE], {"data": [QUOTE]}, [{"data": [QUOTE]}]])
def test_catalog_reference_shapes_and_ruble_token_units(data):
    (quote,) = parse_models(data)
    assert quote.id == MODEL
    assert quote.prompt_rub == Decimal("0.00030631848")
    assert "306.32 ₽/млн" in quote.label
    assert "1531.59 ₽/млн" in quote.label


@pytest.mark.parametrize(
    "patch",
    [
        {"pricing_units": {"prompt": "request", "completion": "token"}},
        {"pricing": {"prompt": "NaN", "completion": "1"}},
        {"pricing": {"prompt": -1, "completion": 1}},
        {"architecture": {"output_modalities": ["image"]}},
        {"supported_parameters": "max_tokens"},
    ],
)
def test_catalog_does_not_mislabel_unsupported_prices_or_models(patch):
    with pytest.raises(ValueError):
        parse_models({"data": [QUOTE | patch]})


@pytest.mark.parametrize(
    "patch",
    [
        {"limit": 0},
        {"limit": None},
        {"limit": "NaN"},
        {"limit": "Infinity"},
        {"limit": "2000.01"},
        {"disabled": True},
        {"disabled": "false"},
        {"usage_monthly": None},
        {"usage_monthly": -1},
        {"usage_monthly": 2000},
        {"limit_remaining": 0},
        {"limit_reset": "daily"},
    ],
)
def test_unbounded_exhausted_or_invalid_key_cannot_start_generation(patch):
    with pytest.raises(ValueError):
        parse_allowance({"data": ALLOWANCE | patch})


def test_allowance_is_monthly_and_never_exceeds_the_declared_remaining():
    allowance = parse_allowance({"data": ALLOWANCE | {"limit_remaining": "12.34"}})
    assert allowance.limit == Decimal(2000)
    assert allowance.remaining == Decimal("12.34")


def test_routerai_payload_uses_only_documented_and_catalog_supported_fields():
    local = {
        "messages": [{"role": "user", "content": "привет"}],
        "options": {"num_predict": 450, "temperature": 0.45},
    }
    profile = CloudProfile("routerai", MODEL, "routerai-test-key")
    assert set(profile.payload(local)) == {"model", "messages", "stream", "temperature"}
    profile = CloudProfile(
        "routerai", MODEL, "routerai-test-key", supported_parameters=("max_tokens",)
    )
    assert profile.payload(local)["max_tokens"] == 450
    assert profile.endpoint == "https://routerai.ru/api/v1/chat/completions"
    assert "routerai-test-key" not in repr(profile)
    with pytest.raises(ValueError):
        CloudProfile("routerai", MODEL + "@provider=expensive", "routerai-test-key")
    with pytest.raises(ValueError):
        CloudProfile("routerai", MODEL, "routerai-test-key", free_only=True)


def test_public_catalog_does_not_send_a_key_or_generate(window, qt_app, monkeypatch):
    with router_server() as (url, records):
        configure(window, monkeypatch, url)
        window.routerai_catalog_button.click()
        wait_for(qt_app, lambda: not window.routerai_catalog.busy)
        assert len(records) == 1
        assert records[0]["path"] == "/api/v1/models" and not records[0]["has_auth"]
        assert window.routerai_model_list.count() == 2
        assert "306.32 ₽/млн" in window.routerai_price.text()
        assert not window._session.turns and not window.ollama.busy


def test_verified_key_then_one_chat_request_and_actual_usage(window, qt_app, monkeypatch):
    with router_server() as (url, records):
        configure(window, monkeypatch, url)
        window.routerai_catalog_button.click()
        wait_for(qt_app, lambda: not window.routerai_catalog.busy)
        window.find_models_button.click()
        assert len(records) == 1  # Applying settings is not generation.
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert [row["path"] for row in records] == [
            "/api/v1/models",
            "/api/v1/key",
            "/api/v1/chat/completions",
        ]
        assert records[1]["method"] == "GET" and records[1]["authenticated"]
        post = records[2]
        assert post["method"] == "POST" and post["authenticated"]
        assert post["body"]["max_tokens"] == 900
        assert "provider" not in post["body"]
        assert len(window._session.turns) == 1
        assert window._session.narrations[0].model == MODEL
        assert "вход 320, выход 75" in window.narrator_details.toPlainText()
        assert "routerai-test-key" not in window.narrator_details.toPlainText()
        assert "routerai-test-key" not in str(window._session.to_dict())


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_key_check_failure_never_sends_a_model_request(window, qt_app, monkeypatch, status):
    with router_server(key_status=status) as (url, records):
        configure(window, monkeypatch, url)
        before = window._session.to_dict(), window._session.dice.checkpoint()
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(records) == 1 and records[0]["path"] == "/api/v1/key"
        assert str(status) in window.narrator_status.text()
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == "осмотрюсь, где я"
        assert "routerai-test-key" not in window.narrator_details.toPlainText()


def test_over_budget_key_is_blocked_before_paid_post(window, qt_app, monkeypatch):
    with router_server(keys=[ALLOWANCE | {"limit": 2001}]) as (url, records):
        configure(window, monkeypatch, url)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(records) == 1 and not window._session.turns
        assert "не более 2000" in window.narrator_status.text()


def test_repair_checks_the_key_again_and_stops_when_allowance_runs_out(window, qt_app, monkeypatch):
    with router_server(keys=[ALLOWANCE, ALLOWANCE | {"limit_remaining": 0}], bad_first=True) as (
        url,
        records,
    ):
        configure(window, monkeypatch, url)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert [row["path"] for row in records] == [
            "/api/v1/key",
            "/api/v1/chat/completions",
            "/api/v1/key",
        ]
        assert "исчерпан" in window.narrator_status.text()
        assert not window._session.turns


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_chat_failure_keeps_engine_attack_and_does_not_repeat_it(
    window, qt_app, monkeypatch, status
):
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window._session = Session.create_hero(Character(), "scout", seed=42)
    with router_server(chat_status=status) as (url, records):
        configure(window, monkeypatch, url)
        window.action_input.setText("ударить стражника ножом")
        window.send_button.click()
        before = window._session.to_dict(), window._session.dice.checkpoint()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(records) == 2
        assert len(window._session.turns) == 1
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == "" and "Промах" in window.journal.toPlainText()
        assert "routerai-test-key" not in window.narrator_details.toPlainText()


def test_cancelling_during_key_check_cannot_start_generation_later(window, qt_app, monkeypatch):
    with router_server(delay_key=0.1) as (url, records):
        configure(window, monkeypatch, url)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: len(records) == 1)
        window.cancel_narration_button.click()
        QTest.qWait(180)
        qt_app.processEvents()
        assert len(records) == 1 and not window.ollama.busy
        assert not window._session.turns
        assert window.action_input.text() == "осмотрюсь, где я"


def test_metadata_redirect_is_not_followed_with_the_key(window, qt_app, monkeypatch):
    with router_server(redirect=True) as (url, records):
        configure(window, monkeypatch, url)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(records) == 1 and not window._session.turns


def test_switching_provider_clears_old_key_and_requires_new_consent(window):
    window.ai_provider.setCurrentIndex(window.ai_provider.findData("openrouter"))
    window.cloud_key.setText("not-a-real-openrouter-key")
    window.cloud_allowed.setChecked(True)
    window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
    assert window.cloud_key.text() == ""
    assert not window.cloud_allowed.isChecked()
    assert window.cloud_model.text() == "deepseek/deepseek-v4-flash-latest"
    assert not window.cloud_free_only.isVisible()


def test_routerai_never_reuses_the_generic_other_provider_environment_key(window, monkeypatch):
    monkeypatch.setenv("RPG_VKR_LLM_API_KEY", "not-a-real-openai-key")
    monkeypatch.delenv("RPG_VKR_ROUTERAI_API_KEY", raising=False)
    window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
    window.cloud_allowed.setChecked(True)
    assert not prepare_model(window)
    assert not window.ollama.busy and "API-ключ" in window.narrator_status.text()


def test_catalog_error_does_not_claim_an_inflight_model_request_was_not_started(
    window, qt_app, monkeypatch
):
    with router_server(delay_key=0.1) as (url, records):
        configure(window, monkeypatch, url)
        window.action_input.setText("осмотрюсь, где я")
        window.send_button.click()
        wait_for(qt_app, lambda: len(records) == 1)
        previous = window.narrator_status.text()
        window.routerai_catalog.failed.emit("Каталог не получен. Генерация не началась.")
        assert window.narrator_status.text() == previous
        window.cancel_narration_button.click()
