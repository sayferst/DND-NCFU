"""Connection UI regressions, independent synthetic metadata and no paid POST."""

import pytest
from test_connection_metadata import metadata_server
from test_local_narrator import wait_for
from test_routerai import MODEL

from rpg_vkr.storage.connection import ConnectionPreferences
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow


@pytest.fixture
def connection_window(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("RPG_VKR_ROUTERAI_API_KEY", raising=False)
    monkeypatch.delenv("RPG_VKR_LLM_API_KEY", raising=False)
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.show()
    from test_developer_access import enter_developer

    enter_developer(qt_app, window, name="Рассказчик")
    qt_app.processEvents()
    try:
        yield window
    finally:
        window.action_input.clear()
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_cloud_panel_does_not_show_an_empty_local_model_control(connection_window):
    assert connection_window.local_model.isHidden()


def test_restart_retains_a_non_flash_selected_model(qt_app, tmp_path, monkeypatch):
    with metadata_server(monkeypatch) as records:
        ConnectionPreferences("routerai", MODEL, True, True).save(tmp_path / "ai-connection.json")
        monkeypatch.setenv("RPG_VKR_ROUTERAI_API_KEY", "synthetic-key")
        window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
        try:
            wait_for(qt_app, lambda: bool(records) and not window._flash_pending)
            assert window.cloud_model.text() == MODEL
            assert window.enable_local_narrator.isChecked()
            assert all(path != "/chat/completions" for path, _ in records)
        finally:
            window.close()


def setup_key(window, model=MODEL):
    window.cloud_key.setText("synthetic-key")
    window.cloud_model.setText(model)
    window.cloud_allowed.setChecked(True)


def test_catalog_loads_without_key_or_consent_and_search_preserves_id(
    connection_window, qt_app, monkeypatch
):
    from test_routerai import QUOTE

    w = connection_window
    rows = [QUOTE, QUOTE | {"id": "author/another-text"}]
    with metadata_server(monkeypatch, catalog={"data": rows}) as records:
        original = w.cloud_model.text()
        w.routerai_catalog_button.click()
        wait_for(qt_app, lambda: len(w._routerai_quotes) == 2)
        assert records == [("/models", False)]
        assert "2 текстовых" in w.catalog_status.text()
        assert not w.cloud_key.text() and not w.cloud_allowed.isChecked()
        assert not w.enable_local_narrator.isChecked()
        w.model_search.setText("another")
        assert w.routerai_model_list.count() == 2
        assert w.cloud_model.text() == original
        assert records == [("/models", False)]


def test_manual_connection_checks_key_without_forcing_catalog_or_flash(
    connection_window, qt_app, monkeypatch
):
    w = connection_window
    setup_key(w)
    with metadata_server(monkeypatch, status=503) as records:
        w.find_models_button.click()
        wait_for(qt_app, lambda: not w._flash_pending)
        assert records == [("/key", True)]
        assert w.enable_local_narrator.isChecked() and w.ai_chat.isChecked()
        assert w.ollama.cloud.model == MODEL
        assert "Ключ проверен" in w.connection_status.text()
        assert "не проверена" in w.connection_status.text()
        assert not w.flash_enabled.isChecked()
        assert ConnectionPreferences.load(w._connection_path).model == MODEL
        assert "synthetic-key" not in w._connection_path.read_text(encoding="utf-8")
        assert not w._credential_path.exists()


@pytest.mark.parametrize("status", [401, 402, 403, 429, 503])
def test_key_http_failure_is_visible_next_to_connection_and_never_posts(
    connection_window, qt_app, monkeypatch, status
):
    w = connection_window
    setup_key(w)
    with metadata_server(monkeypatch, key_status=status) as records:
        before = w._session.to_dict(), w._session.dice.checkpoint()
        w.find_models_button.click()
        wait_for(qt_app, lambda: not w._flash_pending)
        assert str(status) in w.connection_status.text()
        assert "synthetic-key" not in w.connection_status.text()
        assert not w.enable_local_narrator.isChecked()
        assert records == [("/key", True)]
        assert (w._session.to_dict(), w._session.dice.checkpoint()) == before


def test_catalog_failure_is_visible_and_does_not_disable_an_applied_connection(
    connection_window, qt_app, monkeypatch
):
    w = connection_window
    setup_key(w)
    with metadata_server(monkeypatch, status=403) as records:
        w.find_models_button.click()
        wait_for(qt_app, lambda: not w._flash_pending)
        w.routerai_catalog_button.click()
        wait_for(qt_app, lambda: not w.routerai_catalog.busy)
        assert "403" in w.catalog_status.text()
        assert w.enable_local_narrator.isChecked()
        assert w.ollama.cloud.model == MODEL
        assert records == [("/key", True), ("/models", False)]
        assert not w.show_api_key.isChecked()


def test_cancel_key_check_does_not_enable_late_or_lose_input(
    connection_window, qt_app, monkeypatch
):
    from PySide6.QtTest import QTest

    w = connection_window
    setup_key(w)
    w.action_input.setText("изучаю незнакомый след")
    with metadata_server(monkeypatch, delay=0.12) as records:
        w.find_models_button.click()
        wait_for(qt_app, lambda: bool(records))
        assert w.cancel_narration_button.isEnabled()
        w.cancel_narration_button.click()
        QTest.qWait(220)
        assert not w._flash_pending and not w.enable_local_narrator.isChecked()
        assert "отменена" in w.connection_status.text()
        assert w.action_input.text() == "изучаю незнакомый след"
        assert records == [("/key", True)]


def test_changed_key_cannot_accept_an_old_success(connection_window, qt_app, monkeypatch):
    w = connection_window
    setup_key(w)
    with metadata_server(monkeypatch, delay=0.1) as records:
        w.find_models_button.click()
        wait_for(qt_app, lambda: bool(records))
        # A programmatic change is also caught by the snapshot, without relying on textEdited.
        w.cloud_key.setText("a-different-synthetic-key")
        wait_for(qt_app, lambda: not w._flash_pending)
        assert not w.enable_local_narrator.isChecked()
        assert not w._flash_pending
        assert "отменена" in w.connection_status.text()


def test_parameters_button_never_changes_provider_or_erases_key(connection_window):
    w = connection_window
    w.ai_provider.setCurrentIndex(w.ai_provider.findData("openai"))
    w.cloud_model.setText("gpt-test")
    w.cloud_key.setText("synthetic-openai-key")
    w.flash_configure.click()
    assert w.ai_provider.currentData() == "openai"
    assert w.cloud_key.text() == "synthetic-openai-key"
    assert w.cloud_model.text() == "gpt-test"


def test_disconnect_drops_applied_profile_but_keeps_key_field(
    connection_window, qt_app, monkeypatch
):
    w = connection_window
    setup_key(w)
    with metadata_server(monkeypatch) as records:
        w.find_models_button.click()
        wait_for(qt_app, lambda: not w._flash_pending)
        w.disconnect_master.click()
        assert not w.enable_local_narrator.isChecked() and w.ollama.cloud is None
        assert w.cloud_key.text() == "synthetic-key"
        assert not ConnectionPreferences.load(w._connection_path).enabled
        assert records == [("/key", True)]


def test_key_mask_is_explicit_and_reset_on_provider_switch(connection_window):
    from PySide6.QtWidgets import QLineEdit

    w = connection_window
    setup_key(w)
    assert w.cloud_key.echoMode() == QLineEdit.EchoMode.Password
    w.show_api_key.click()
    assert w.cloud_key.echoMode() == QLineEdit.EchoMode.Normal
    w.ai_provider.setCurrentIndex(w.ai_provider.findData("openai"))
    assert w.cloud_key.echoMode() == QLineEdit.EchoMode.Password
    assert not w.cloud_key.text()


def test_primary_controls_are_visible_and_diagnostics_are_collapsed(connection_window):
    w = connection_window
    assert w.ai_provider.isVisible() and w.cloud_key.isVisible()
    assert w.find_models_button.isVisible() and w.cancel_narration_button.isVisible()
    assert not w.connection_advanced.isChecked()
    assert not w.narrator_context.isVisible()
    assert not w.connection_storage.isChecked()
    w.connection_advanced.click()
    assert w.narrator_context.isVisible()
    assert w.ai_chat.isChecked() and w.world_agent.isChecked()


def test_saving_invalid_model_is_reported_without_removing_credential(connection_window):
    w = connection_window
    w._credential_path.write_bytes(b"previous-encrypted-credential")
    w.cloud_model.setText("invalid model id with spaces")
    w.connection_save.click()
    assert "Не удалось сохранить" in w.connection_status.text()
    assert w._credential_path.read_bytes() == b"previous-encrypted-credential"


def test_other_provider_env_key_cannot_verify_routerai(connection_window, monkeypatch):
    w = connection_window
    monkeypatch.setenv("RPG_VKR_LLM_API_KEY", "other-provider-synthetic-key")
    w.cloud_allowed.setChecked(True)
    with metadata_server(monkeypatch) as records:
        w.find_models_button.click()
        assert not w._flash_pending and not records
        assert "API-ключ" in w.connection_status.text()


def test_explicit_last_key_replaces_previous_and_restores_masked_without_connecting(
    connection_window, qt_app, monkeypatch
):
    from PySide6.QtWidgets import QLineEdit

    import rpg_vkr.ui.flash_settings as controls

    w = connection_window
    vault = {}

    def encrypt(path, key):
        vault[str(path)] = key
        path.write_bytes(b"synthetic-encrypted-envelope")

    monkeypatch.setattr(controls, "save_secret", encrypt)
    monkeypatch.setattr(controls, "load_secret", lambda path: vault.get(str(path), ""))
    setup_key(w)
    controls.save_last_key(w)
    w.cloud_key.setText("newest-synthetic-key")
    controls.save_last_key(w)
    assert vault[str(w._credential_path)] == "newest-synthetic-key"
    assert w.remember_key.isChecked()
    assert "зашифрованном" in w.connection_status.text()
    assert b"newest-synthetic-key" not in w._credential_path.read_bytes()
    assert "newest-synthetic-key" not in w._connection_path.read_text(encoding="utf-8")
    assert not w.enable_local_narrator.isChecked()
    restored = MainWindow(saves=SaveSlots(w._saves.directory))
    try:
        qt_app.processEvents()
        assert restored.cloud_key.text() == "newest-synthetic-key"
        assert restored.cloud_key.echoMode() == QLineEdit.EchoMode.Password
        assert not restored._flash_pending and not restored.enable_local_narrator.isChecked()
    finally:
        restored.close()


def test_invalid_last_key_does_not_overwrite_previous_ciphertext(connection_window):
    from rpg_vkr.ui.flash_settings import save_last_key

    w = connection_window
    w._credential_path.write_bytes(b"previous-encrypted-key")
    w.cloud_key.setText("Bearer invalid synthetic key")
    save_last_key(w)
    assert w._credential_path.read_bytes() == b"previous-encrypted-key"
    assert "Ключ не сохранён" in w.connection_status.text()
    assert "Bearer invalid" not in w.connection_status.text()


def test_failed_encryption_preserves_previous_ciphertext(connection_window, monkeypatch):
    import rpg_vkr.ui.flash_settings as controls

    w = connection_window
    setup_key(w)
    w._credential_path.write_bytes(b"previous-encrypted-key")

    def fail(*args):
        raise OSError("synthetic encryption failure")

    monkeypatch.setattr(controls, "save_secret", fail)
    controls.save_last_key(w)
    assert w._credential_path.read_bytes() == b"previous-encrypted-key"
    assert not w.remember_key.isChecked()
    assert "Ключ не сохранён" in w.connection_status.text()


def test_remember_choice_saves_latest_key_on_successful_connection(
    connection_window, qt_app, monkeypatch
):
    import rpg_vkr.ui.flash_settings as controls

    w = connection_window
    saved = []
    monkeypatch.setattr(controls, "save_secret", lambda path, key: saved.append(key))
    setup_key(w)
    w.remember_key.setChecked(True)
    w.cloud_key.setText("latest-synthetic-key")
    with metadata_server(monkeypatch) as records:
        w.find_models_button.click()
        wait_for(qt_app, lambda: not w._flash_pending)
        assert saved == ["latest-synthetic-key"]
        assert w.enable_local_narrator.isChecked()
        assert records == [("/key", True)]
