"""Separate Master/Artist workflows: real Qt, synthetic keys and GET-only loopback."""

import pytest
from PySide6.QtWidgets import QLineEdit
from test_connection_metadata import metadata_server
from test_local_narrator import wait_for
from test_visual_policy import catalog

from rpg_vkr.storage.artist_connection import ArtistPreferences
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.visuals.client import ImagesTransport
from rpg_vkr.visuals.policy import FLUX, RECRAFT


@pytest.fixture
def artist_window(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("RPG_VKR_ROUTERAI_API_KEY", raising=False)
    monkeypatch.delenv("RPG_VKR_LLM_API_KEY", raising=False)
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.show()
    from test_developer_access import enter_developer

    enter_developer(qt_app, window, name="Художник")
    qt_app.processEvents()
    try:
        yield window
    finally:
        wait_for(qt_app, lambda: not window.artist_panel._inflight)
        window.action_input.clear()
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def image_catalog():
    return {"data": [*catalog(RECRAFT, "0.75")["data"], *catalog(FLUX, "0.97")["data"]]}


def local_transport(panel):
    import rpg_vkr.narrative.routerai as api

    panel.worker.transport = ImagesTransport(test_base=api.KEY_URL.rsplit("/", 1)[0])


def finish(panel, qt_app):
    wait_for(qt_app, lambda: not panel._inflight)


def test_two_named_panels_and_backward_navigation(artist_window):
    w = artist_window
    names = [w.navigation.itemText(i) for i in range(w.navigation.count())]
    assert "Мастер" not in names and "Художник" not in names
    assert "Рассказчик" not in names
    w.open_section("Рассказчик")
    assert w.tabs.currentWidget() is w.developer_console
    assert w.developer_console.pages.currentWidget() is w.developer_console.originals["Мастер"]
    w.open_section("Художник")
    assert w.artist_panel.key_input.isVisible()
    assert w.artist_panel.model_choice.isVisible()


def test_two_model_names_ids_and_search_are_always_available(artist_window):
    panel = artist_window.artist_panel
    assert panel.model_choice.count() == 2
    assert "Recraft V4.1 Flash" in panel.model_choice.itemText(0)
    assert "FLUX 3 Image Klein" in panel.model_choice.itemText(1)
    assert {panel.model_choice.itemData(i) for i in range(2)} == {RECRAFT, FLUX}
    assert "не проверена" in panel.model_choice.itemText(0)
    panel.search.setText("flux")
    assert panel.model_choice.count() == 1 and panel.model_id.text() == FLUX
    panel.search.setText("does-not-exist")
    assert panel.model_choice.count() == 0 and not panel.model_id.text()
    panel.search.clear()
    assert panel.model_choice.count() == 2


def test_own_key_is_independent_and_empty_own_key_never_falls_back(artist_window):
    w = artist_window
    panel = w.artist_panel
    w.cloud_key.setText("master-synthetic-key")
    assert w.visuals.key() == "master-synthetic-key"
    assert panel.key_input.text() == "master-synthetic-key" and not panel.key_input.isEnabled()
    panel.shared_key.setChecked(False)
    assert w.visuals.key() == ""
    panel.key_input.setText("artist-synthetic-key")
    assert w.visuals.key() == "artist-synthetic-key"
    assert w.cloud_key.text() == "master-synthetic-key"
    panel.shared_key.setChecked(True)
    assert w.visuals.key() == "master-synthetic-key"
    panel.shared_key.setChecked(False)
    assert w.visuals.key() == "artist-synthetic-key"


def test_artist_never_uses_openai_key_as_a_routerai_key(artist_window, monkeypatch):
    w = artist_window
    w.ai_provider.setCurrentIndex(w.ai_provider.findData("openai"))
    w.cloud_key.setText("openai-synthetic-key")
    monkeypatch.setenv("RPG_VKR_LLM_API_KEY", "generic-synthetic-key")
    assert w.visuals.key() == "" and not w.artist_panel.key_input.text()


def test_public_image_catalog_loads_without_a_key_or_spending(artist_window, qt_app, monkeypatch):
    w = artist_window
    panel = w.artist_panel
    before = w._session.to_dict(), w._session.dice.checkpoint()
    with metadata_server(monkeypatch, catalog=image_catalog()) as records:
        local_transport(panel)
        panel.catalog_button.click()
        finish(panel, qt_app)
        assert records == [("/models", False)]
        assert "2 из 2" in panel.catalog_status.text()
        assert all("есть в каталоге" in panel.model_choice.itemText(i) for i in range(2))
        assert "0.7500" in panel.model_details.text()
        assert not w.visuals.registry.ledger()
        assert (w._session.to_dict(), w._session.dice.checkpoint()) == before


def test_own_key_verification_is_get_only_and_does_not_change_master(
    artist_window, qt_app, monkeypatch
):
    w = artist_window
    panel = w.artist_panel
    w.cloud_key.setText("master-synthetic-key")
    master = (w.cloud_model.text(), w.cloud_key.text(), w.enable_local_narrator.isChecked())
    panel.shared_key.setChecked(False)
    panel.key_input.setText("artist-synthetic-key")
    with metadata_server(monkeypatch, catalog=image_catalog()) as records:
        local_transport(panel)
        panel.check_button.click()
        finish(panel, qt_app)
        assert records == [("/key", True), ("/models", False)]
        assert "Ключ Художника проверен" in panel.connection_status.text()
        assert (
            w.cloud_model.text(),
            w.cloud_key.text(),
            w.enable_local_narrator.isChecked(),
        ) == master
        assert not w.visuals.registry.ledger()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_artist_key_error_is_local_and_redacted(artist_window, qt_app, monkeypatch, status):
    panel = artist_window.artist_panel
    panel.shared_key.setChecked(False)
    panel.key_input.setText("artist-synthetic-key")
    with metadata_server(monkeypatch, key_status=status) as records:
        local_transport(panel)
        panel.check_button.click()
        finish(panel, qt_app)
        assert str(status) in panel.connection_status.text()
        assert "artist-synthetic-key" not in panel.connection_status.text()
        assert records == [("/key", True)]


def test_cancelled_or_changed_key_check_cannot_apply_a_late_success(
    artist_window, qt_app, monkeypatch
):
    panel = artist_window.artist_panel
    panel.shared_key.setChecked(False)
    panel.key_input.setText("artist-synthetic-key")
    with metadata_server(monkeypatch, catalog=image_catalog(), delay=0.1) as records:
        local_transport(panel)
        panel.check_button.click()
        wait_for(qt_app, lambda: bool(records))
        panel.key_input.setText("changed-synthetic-key")
        finish(panel, qt_app)
        assert panel.catalog is None
        assert "изменён" in panel.connection_status.text()
        assert not artist_window.visuals.registry.ledger()


def test_model_missing_or_unknown_tariff_is_visible_not_invented(
    artist_window, qt_app, monkeypatch
):
    panel = artist_window.artist_panel
    with metadata_server(monkeypatch, catalog={"data": [{"id": RECRAFT}]}) as records:
        local_transport(panel)
        panel.catalog_button.click()
        finish(panel, qt_app)
        assert "1 из 2" in panel.catalog_status.text()
        assert "не найдена" in panel.model_choice.itemText(1)
        assert "не подтверждены" in panel.model_details.text()
        assert records == [("/models", False)]


def test_separate_encrypted_key_replaces_restores_and_never_overwrites_master(
    artist_window, qt_app, monkeypatch
):
    import rpg_vkr.ui.artist_panel as ui

    w = artist_window
    panel = w.artist_panel
    vault = {}
    w._credential_path.write_bytes(b"previous-master-ciphertext")

    def encrypt(path, key):
        vault[str(path)] = key
        path.write_bytes(b"synthetic-artist-ciphertext")

    monkeypatch.setattr(ui, "save_secret", encrypt)
    monkeypatch.setattr(ui, "load_secret", lambda path: vault.get(str(path), ""))
    panel.shared_key.setChecked(False)
    panel.key_input.setText("first-artist-synthetic-key")
    panel.save_key()
    panel.key_input.setText("latest-artist-synthetic-key")
    panel.save_key()
    assert vault[str(panel.credential_path)] == "latest-artist-synthetic-key"
    assert w._credential_path.read_bytes() == b"previous-master-ciphertext"
    assert "latest-artist-synthetic-key" not in panel.path.read_text(encoding="utf-8")
    assert b"latest-artist-synthetic-key" not in panel.credential_path.read_bytes()
    restored = MainWindow(saves=SaveSlots(w._saves.directory))
    try:
        qt_app.processEvents()
        p = restored.artist_panel
        assert not p.shared_key.isChecked()
        assert p.key_input.text() == "latest-artist-synthetic-key"
        assert p.key_input.echoMode() == QLineEdit.EchoMode.Password
        assert not p.worker.busy
    finally:
        restored.close()


def test_forget_artist_key_keeps_master_and_current_session_field(artist_window):
    w = artist_window
    panel = w.artist_panel
    w._credential_path.write_bytes(b"master-ciphertext")
    panel.credential_path.write_bytes(b"artist-ciphertext")
    panel.shared_key.setChecked(False)
    panel.key_input.setText("artist-synthetic-key")
    panel.forget_key_button.click()
    assert not panel.credential_path.exists()
    assert w._credential_path.read_bytes() == b"master-ciphertext"
    assert panel.key_input.text() == "artist-synthetic-key"


def test_budget_is_in_artist_panel_and_keeps_approved_limits(artist_window):
    w = artist_window
    w.artist_panel.show_budget()
    assert w.visuals.monthly.isVisible() and w.visuals.consent.isVisible()
    assert w.visuals.economy.maximum() == 5 and w.visuals.quality.maximum() == 10
    assert w.visuals.settings.monthly_micros == 0
    assert w.visuals.settings.confirm and not w.visuals.settings.consent


def test_unknown_artist_preferences_do_not_load_keys(tmp_path):
    p = tmp_path / "artist.json"
    p.write_text('{"api_key":"synthetic-secret"}', encoding="utf-8")
    assert ArtistPreferences.load(p) == ArtistPreferences()


def test_cancel_check_ignores_late_catalog_and_does_not_start_a_second_worker(
    artist_window, qt_app, monkeypatch
):
    panel = artist_window.artist_panel
    with metadata_server(monkeypatch, catalog=image_catalog(), delay=0.08) as records:
        local_transport(panel)
        panel.catalog_button.click()
        wait_for(qt_app, lambda: bool(records))
        panel.cancel_check.click()
        panel.check("catalog")
        finish(panel, qt_app)
        assert records == [("/models", False)]
        assert panel.catalog is None and "отменена" in panel.connection_status.text()
        assert panel.catalog_button.isEnabled()


def test_bad_or_failed_saved_artist_key_keeps_old_envelope(artist_window, monkeypatch):
    import rpg_vkr.ui.artist_panel as ui

    panel = artist_window.artist_panel
    panel.shared_key.setChecked(False)
    panel.credential_path.write_bytes(b"old-artist-ciphertext")
    panel.key_input.setText("Bearer invalid key")
    assert panel.save_key() is False
    assert panel.credential_path.read_bytes() == b"old-artist-ciphertext"

    def fail(*args):
        raise OSError("synthetic encryption failure")

    monkeypatch.setattr(ui, "save_secret", fail)
    panel.key_input.setText("valid-shaped-synthetic-key")
    assert panel.save_key() is False
    assert panel.credential_path.read_bytes() == b"old-artist-ciphertext"


def test_selecting_image_model_never_changes_master_or_starts_generation(artist_window):
    w = artist_window
    panel = w.artist_panel
    before = w.cloud_model.text(), w._session.to_dict(), w._session.dice.checkpoint()
    panel.model_choice.setCurrentIndex(1)
    panel.model_choice.activated.emit(1)
    assert panel.model_id.text() == FLUX
    assert (w.cloud_model.text(), w._session.to_dict(), w._session.dice.checkpoint()) == before
    assert not panel.worker.busy and not w.visuals.worker.busy and not w.visuals.registry.ledger()


def test_render_uses_artist_own_key_and_keeps_world_unchanged(qt_app, tmp_path):
    from dataclasses import replace

    from response_cases import new_session
    from test_visual_controller import FakeTransport

    from rpg_vkr.ui.knowledge import knowledge_entries
    from rpg_vkr.visuals.context import entity_target

    class KeySpy(FakeTransport):
        def __init__(self):
            super().__init__()
            self.keys = []

        def metadata(self, key):
            self.keys.append(("metadata", key))
            return super().metadata(key)

        def generate(self, body, key):
            self.keys.append(("generate", key))
            return super().generate(body, key)

    w = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    w._confirm = lambda *_: True
    try:
        controller = w.visuals
        transport = KeySpy()
        controller.worker.transport = transport
        controller.ask = lambda *_: True
        controller.view = lambda *_: None
        controller.settings = replace(controller.settings, consent=True, monthly_micros=10000000)
        w.cloud_key.setText("master-synthetic-key")
        w.artist_panel.shared_key.setChecked(False)
        w.artist_panel.key_input.setText("artist-synthetic-key")
        entry = next(e for e in knowledge_entries(w._session) if e.category == "items")
        before = w._session.to_dict(), w._session.dice.checkpoint()
        controller.request(entity_target(w._session, entry))
        wait_for(qt_app, lambda: not controller.active and not controller.worker.busy)
        assert transport.keys == [
            ("metadata", "artist-synthetic-key"),
            ("generate", "artist-synthetic-key"),
        ]
        assert len(transport.posts) == 1 and transport.posts[0]["model"] == RECRAFT
        assert (w._session.to_dict(), w._session.dice.checkpoint()) == before
        assert all("synthetic-key" not in str(r) for r in controller.registry.ledger())
    finally:
        w.close()


def test_artist_explains_a_new_key_without_monthly_limit(artist_window, qt_app, monkeypatch):
    import test_connection_metadata as endpoint
    from test_routerai import ALLOWANCE

    monkeypatch.setattr(endpoint, "ALLOWANCE", ALLOWANCE | {"limit": 0})
    panel = artist_window.artist_panel
    panel.shared_key.setChecked(False)
    panel.key_input.setText("artist-synthetic-key")
    with metadata_server(monkeypatch, catalog=image_catalog()) as records:
        local_transport(panel)
        panel.check_button.click()
        finish(panel, qt_app)
        assert "положительный месячный лимит" in panel.connection_status.text()
        assert records == [("/key", True)]


def test_public_catalog_can_finish_while_the_artist_key_is_entered(
    artist_window, qt_app, monkeypatch
):
    panel = artist_window.artist_panel
    with metadata_server(monkeypatch, catalog=image_catalog(), delay=0.1) as records:
        local_transport(panel)
        panel.catalog_button.click()
        wait_for(qt_app, lambda: bool(records))
        panel.shared_key.setChecked(False)
        panel.key_input.setText("artist-synthetic-key")
        finish(panel, qt_app)
        assert panel.catalog is not None and "2 из 2" in panel.catalog_status.text()
        assert records == [("/models", False)]
