"""Interactive play requires a deliberately configured cloud storyteller."""

import os

from PySide6.QtWidgets import QMessageBox

NOTICE = (
    "Включите облачного ИИ-мастера в настройках и разрешите отправку сцены. Реплика не выполнена."
)


def cloud_ready(window):
    return (
        window.ai_provider.currentData() != "local"
        and window.enable_local_narrator.isChecked()
        and window.ai_chat.isChecked()
        and window.cloud_allowed.isChecked()
        and bool(window.cloud_model.text().strip())
        and bool(
            window.cloud_key.text().strip()
            or os.environ.get(
                "RPG_VKR_ROUTERAI_API_KEY"
                if window.ai_provider.currentData() == "routerai"
                else "RPG_VKR_LLM_API_KEY",
                "",
            )
        )
        and not getattr(window, "_flash_pending", False)
    )


def require_cloud(window):
    if window._legacy_controls or cloud_ready(window):
        return True
    window.narrator_status.setText(NOTICE)
    window.statusBar().showMessage(NOTICE)
    QMessageBox.information(window, "Нужен онлайн-мастер", NOTICE)
    return False
