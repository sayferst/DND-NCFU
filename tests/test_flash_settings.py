"""Flash controls: real Qt + loopback metadata, never a live or paid request."""

import json

import pytest
from PySide6.QtWidgets import QApplication
from test_local_narrator import wait_for
from test_routerai import ALLOWANCE, configure, router_server

from rpg_vkr.storage import connection
from rpg_vkr.storage.connection import FLASH_MODEL, ConnectionPreferences
from rpg_vkr.ui.flash_settings import generation_status, save_connection


@pytest.fixture
def flash(window, monkeypatch):
    import test_routerai

    monkeypatch.delenv("RPG_VKR_ROUTERAI_API_KEY", raising=False)
    monkeypatch.setattr(test_routerai, "MODEL", FLASH_MODEL)
    monkeypatch.setitem(test_routerai.QUOTE, "id", FLASH_MODEL)
    return window


def test_flash_verifies_key_then_model_without_generating(flash, monkeypatch):
    with router_server() as (url, requests):
        configure(flash, monkeypatch, url)
        flash.flash_enabled.setChecked(True)
        wait_for(QApplication.instance(), lambda: flash._flash_verified)
        assert [(r["method"], r["path"]) for r in requests] == [
            ("GET", "/api/v1/key"),
            ("GET", "/api/v1/models"),
        ]
        assert flash.enable_local_narrator.isChecked()
        assert flash.ollama.cloud.model == FLASH_MODEL
        assert "Подключён" in flash.flash_status.text()
        preferences = json.loads(flash._connection_path.read_text(encoding="utf-8"))
        assert preferences == dict(
            provider="routerai", model=FLASH_MODEL, enabled=True, consent=True
        )
        assert "routerai-test-key" not in json.dumps(preferences)
        assert "routerai-test-key" not in json.dumps(flash._session.to_dict())
        flash.flash_enabled.setChecked(False)
        assert not flash.enable_local_narrator.isChecked()
        assert len(requests) == 2
        assert not ConnectionPreferences.load(flash._connection_path).enabled


@pytest.mark.parametrize("missing", ["key", "consent"])
def test_missing_configuration_never_calls_api(flash, monkeypatch, missing):
    with router_server() as (url, requests):
        configure(flash, monkeypatch, url)
        if missing == "key":
            flash.cloud_key.clear()
        else:
            flash.cloud_allowed.setChecked(False)
        flash.flash_enabled.setChecked(True)
        assert not flash.flash_enabled.isChecked()
        assert "Не настроен" in flash.flash_status.text()
        assert not requests


@pytest.mark.parametrize("mode", ["invalid_key", "empty_balance", "missing_model"])
def test_flash_rejects_invalid_metadata_without_paid_substitution(flash, monkeypatch, mode):
    import test_routerai

    if mode == "missing_model":
        monkeypatch.setitem(test_routerai.QUOTE, "id", "deepseek/other")
    options = (
        {"key_status": 401}
        if mode == "invalid_key"
        else {"keys": [{**ALLOWANCE, "limit_remaining": "0"}]}
        if mode == "empty_balance"
        else {}
    )
    with router_server(**options) as (url, requests):
        configure(flash, monkeypatch, url)
        flash.flash_enabled.setChecked(True)
        wait_for(QApplication.instance(), lambda: not flash._flash_pending)
        assert not flash.flash_enabled.isChecked()
        assert not flash.enable_local_narrator.isChecked()
        assert all(r["method"] == "GET" for r in requests)
        assert len(requests) == (2 if mode == "missing_model" else 1)
        assert "routerai-test-key" not in flash.flash_status.text()
        assert (
            "Лимит исчерпан" in flash.flash_status.text()
            if mode == "empty_balance"
            else ("Не настроен" in flash.flash_status.text())
        )


def test_cancelled_check_preserves_input_and_never_enables_later(flash, monkeypatch):
    from PySide6.QtTest import QTest

    with router_server(delay_key=0.1) as (url, requests):
        configure(flash, monkeypatch, url)
        flash.flash_enabled.setChecked(True)
        flash.action_input.setText("спрашиваю прохожего о дороге")
        before = flash._session.to_dict()
        flash.submit_action()
        assert flash._session.to_dict() == before
        assert flash.action_input.text() == "спрашиваю прохожего о дороге"
        flash.flash_enabled.setChecked(False)
        QTest.qWait(180)
        assert not flash._flash_verified and not flash.enable_local_narrator.isChecked()
        assert all(r["method"] == "GET" for r in requests)
        flash.action_input.clear()


def test_changing_provider_invalidates_verified_flash(flash, monkeypatch):
    with router_server() as (url, _):
        configure(flash, monkeypatch, url)
        flash.flash_enabled.setChecked(True)
        wait_for(QApplication.instance(), lambda: flash._flash_verified)
        flash.ai_provider.setCurrentIndex(flash.ai_provider.findData("local"))
        assert not flash.flash_enabled.isChecked() and not flash._flash_verified
        assert not ConnectionPreferences.load(flash._connection_path).enabled


def test_restarting_without_key_preserves_menu_and_does_not_connect(qt_app, tmp_path, monkeypatch):
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.main_window import MainWindow

    monkeypatch.delenv("RPG_VKR_ROUTERAI_API_KEY", raising=False)
    ConnectionPreferences("routerai", FLASH_MODEL, True, True).save(tmp_path / "ai-connection.json")
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    qt_app.processEvents()
    try:
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Главное меню"
        assert not window._flash_pending and not window.ollama.busy
        assert not window.flash_enabled.isChecked()
        assert "Не настроен" in window.flash_status.text()
    finally:
        window.close()


def test_preferences_are_bounded_and_exclude_unknown_secret_fields(tmp_path):
    path = tmp_path / "preferences.json"
    for text in ['{"key":"secret"}', "[]", "x" * 4097, '{"enabled":1}']:
        path.write_text(text, encoding="utf-8")
        assert ConnectionPreferences.load(path) == ConnectionPreferences()
    ConnectionPreferences("routerai", FLASH_MODEL, True, True).save(path)
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "provider",
        "model",
        "enabled",
        "consent",
    }


def test_secret_file_is_ciphertext_only_with_explicit_crypto_mock(tmp_path, monkeypatch):
    # Envelope/storage test only: actual Windows DPAPI needs a Windows manual check.
    monkeypatch.setattr(
        connection, "_dpapi", lambda data, decrypt=False: bytes(b ^ 97 for b in data)
    )
    path = tmp_path / "credential.bin"
    connection.save_secret(path, "synthetic-test-key")
    assert b"synthetic-test-key" not in path.read_bytes()
    assert connection.load_secret(path) == "synthetic-test-key"
    path.write_bytes(b"plaintext-synthetic-test-key")
    assert connection.load_secret(path) == ""


def test_no_plaintext_fallback_if_secure_storage_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(connection, "windows_credentials_available", lambda: False)
    path = tmp_path / "credential.bin"
    with pytest.raises(OSError):
        connection.save_secret(path, "synthetic-test-key")
    assert not path.exists()


def test_forgetting_secret_and_saving_connection_stays_nonsecret(flash):
    flash.ai_provider.setCurrentIndex(flash.ai_provider.findData("routerai"))
    flash.cloud_key.setText("synthetic-test-key")
    flash._credential_path.write_bytes(b"previous-ciphertext")
    flash.remember_key.setChecked(False)
    save_connection(flash)
    assert not flash._credential_path.exists()
    assert "synthetic-test-key" not in flash._connection_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "message,label",
    [
        ("HTTP 429", "Лимит исчерпан"),
        ("HTTP 402", "Лимит исчерпан"),
        ("HTTP 401", "Не настроен"),
        ("Модель отсутствует", "Не настроен"),
        ("Сеть недоступна", "Нет соединения"),
    ],
)
def test_status_reports_actual_failure_class(flash, message, label):
    generation_status(flash, message, force=True)
    assert flash.flash_status.text().startswith(label)


def test_restart_with_consented_env_key_checks_metadata_only(flash, qt_app, tmp_path, monkeypatch):
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.main_window import MainWindow

    with router_server() as (url, requests):
        configure(flash, monkeypatch, url)
        directory = tmp_path / "restart"
        ConnectionPreferences("routerai", FLASH_MODEL, True, True).save(
            directory / "ai-connection.json"
        )
        monkeypatch.setenv("RPG_VKR_ROUTERAI_API_KEY", "routerai-test-key")
        restored = MainWindow(saves=SaveSlots(directory / "saves"))
        try:
            wait_for(qt_app, lambda: restored._flash_verified)
            assert restored.tabs.tabText(restored.tabs.currentIndex()) == "Главное меню"
            assert len(requests) == 2 and all(r["method"] == "GET" for r in requests)
            assert restored.cloud_model.text() == FLASH_MODEL
        finally:
            restored.close()
