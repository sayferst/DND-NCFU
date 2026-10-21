"""Minimal activation, automatic approved models, no owner API key in a tester build."""

from PySide6.QtWidgets import QInputDialog, QLineEdit, QPushButton

from rpg_vkr.deployment import load_release_profile, tester_token
from rpg_vkr.narrative.cloud import CloudProfile
from rpg_vkr.storage.connection import load_secret, save_secret, windows_credentials_available
from rpg_vkr.visuals.client import ImagesTransport
from rpg_vkr.visuals.policy import VisualSettings

_probe_offline = False


def install_tester_connection(window):
    if _probe_offline:
        from rpg_vkr.deployment import ReleaseProfile

        window.release_profile = ReleaseProfile()
    else:
        window.release_profile = load_release_profile()
    profile = window.release_profile
    console = window.developer_console
    console.testing_info.setText(
        f"Профиль: {profile.mode} · сборка {profile.commit}\n"
        + (
            "Сервер: " + profile.gateway
            if profile.gateway
            else "Сервер для тестировщиков не задан."
        )
    )
    if profile.mode != "tester":
        return
    window._tester_token = load_secret(window._saves.directory.parent / "tester-access.bin")
    # Drop owner settings applied during initialization, even if this PC has an owner key.
    window.cloud_key.clear()
    window.ollama.use_local()
    window.enable_local_narrator.setChecked(False)
    window._flash_pending = False
    window.routerai_catalog.cancel()
    window.routerai_key_client.cancel()
    window.cloud_model.setText(profile.text_model)
    window.local_model.clear()
    window.local_model.addItem(profile.text_model)
    for widget in console.originals.values():
        widget.setEnabled(False)
    activate_button = QPushButton("Активировать допуск тестировщика…")
    activate_button.clicked.connect(lambda: activate(window))
    window.settings_form.addRow(activate_button)
    for index in range(window.tabs.count()):
        page = window.tabs.widget(index)
        if window.tabs.tabText(index) == "Главное меню":
            page.activation_button = QPushButton("Активировать тестовую игру")
            page.activation_button.clicked.connect(lambda: activate(window))
            page.layout().insertWidget(page.layout().count() - 2, page.activation_button)
    if profile.discovery:
        from rpg_vkr.ui.tester_discovery import ConnectionWorker

        window._tester_endpoint = ""
        window.tester_connection_worker = ConnectionWorker(window)
    else:
        configure(window)


def configure(window):
    profile = window.release_profile
    token = tester_token(window)
    endpoint = getattr(window, "_tester_endpoint", profile.gateway)
    if not endpoint or not token:
        return False
    window.cloud_model.setText(profile.text_model)
    window.cloud_allowed.setChecked(True)
    window.ai_chat.setChecked(True)
    window.world_agent.setChecked(True)
    window.enable_local_narrator.setChecked(True)
    window.ollama.configure_cloud(
        CloudProfile(
            "gateway", profile.text_model, token, endpoint_url=endpoint + "/chat/completions"
        )
    )
    if hasattr(window, "visuals"):
        visual = window.visuals
        visual.worker.transport = ImagesTransport(gateway_base=endpoint, gateway_key=token)
        # Server owns the true quota; local limits remain conservative as well.
        visual.settings = VisualSettings(
            monthly_micros=2_000_000_000,
            economy_cap=5_000_000,
            quality_cap=10_000_000,
            consent=True,
        )
    return True


def activate(window):
    if window.release_profile.discovery:
        window.tester_connection_worker.start()
        return False
    if not window.release_profile.gateway:
        window.statusBar().showMessage(
            "В этой сборке игровой сервер ещё не указан. Обратитесь к владельцу."
        )
        return False
    token, ok = QInputDialog.getText(
        window,
        "Допуск к тестированию",
        "Введите персональный код от владельца игры",
        QLineEdit.EchoMode.Password,
    )
    if not ok:
        return False
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token.strip()):
        window.statusBar().showMessage("Проверьте код допуска.")
        return False
    window._tester_token = token.strip()
    if windows_credentials_available():
        try:
            save_secret(window._saves.directory.parent / "tester-access.bin", window._tester_token)
        except (ValueError, OSError):
            window.statusBar().showMessage(
                "Допуск действует в этом сеансе; сохранить его не удалось."
            )
    configured = configure(window)
    window.statusBar().showMessage(
        "Допуск применён. Доступность сервера проверится при начале приключения."
    )
    return configured
