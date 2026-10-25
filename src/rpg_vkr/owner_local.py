"""Private owner build binding and direct access to the locally protected admin key."""

import base64
import json
import os
from pathlib import Path

from rpg_vkr.storage.connection import _dpapi, load_secret


def machine_id():
    if os.name != "nt":
        raise ValueError("Личная сборка доступна только на Windows владельца.")
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ) as key:
        return winreg.QueryValueEx(key, "MachineGuid")[0]


def create_binding():
    payload = json.dumps({"version": 1, "machine": machine_id()}).encode()
    return base64.b64encode(_dpapi(payload)).decode("ascii")


def verify_binding(binding):
    try:
        value = json.loads(_dpapi(base64.b64decode(binding, validate=True), decrypt=True))
        if value != {"version": 1, "machine": machine_id()}:
            raise ValueError
    except (ValueError, OSError, TypeError):
        raise ValueError(
            "Эта личная сборка привязана к другому ПК или пользователю Windows. "
            "Пересоберите её через BUILD_EXE.bat на ПК владельца."
        ) from None


def admin_key():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "DND-NCFU-Host"
    key = load_secret(root / "account-admin-key.bin")
    if not key:
        raise ValueError("Сначала сохраните ключ admin через CHANGE_ADMIN_API.bat.")
    return key


def install_owner(window):
    # Validate before exposing the window. Never fall back to an unbound profile or key.
    verify_binding(window.release_profile.owner_binding)
    key = admin_key()
    from PySide6.QtCore import QTimer

    from rpg_vkr.ui.narrator_panel import prepare_model, refresh_narrator_panels
    from rpg_vkr.visuals.client import ImagesTransport

    window._account_name = "admin"
    window.developer_console.access.authorized = True

    def configure():
        if getattr(window, "_closing", False):
            return
        window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
        window.cloud_key.setText(key)
        window.cloud_model.setText(window.release_profile.text_model)
        window.cloud_allowed.setChecked(True)
        window.ai_chat.setChecked(True)
        window.world_agent.setChecked(True)
        window.enable_local_narrator.setChecked(True)
        if not prepare_model(window):
            return
        window._flash_verified = False
        window._flash_pending = False
        window.artist_panel.shared_key.setChecked(True)
        window.artist_panel.sync_key()
        window.visuals.worker.transport = ImagesTransport()
        from dataclasses import replace

        window.visuals.settings = replace(window.visuals.settings, consent=True)
        refresh_narrator_panels(window)
        window.connection_status.setText(
            "Личный ключ admin применён. Доступ проверится с первым запросом."
        )
        window.statusBar().showMessage(
            "Личная проверка · admin · прямое подключение RouterAI без хоста."
        )

    QTimer.singleShot(0, configure)
