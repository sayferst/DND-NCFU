"""Interactive play requires a deliberately configured cloud storyteller."""

import os

from PySide6.QtWidgets import QMessageBox

NOTICE = (
    "Игровой мастер пока недоступен. Проверьте интернет или обратитесь к владельцу игры. "
    "Ваш герой и сохранения остаются на компьютере."
)


def cloud_ready(window):
    if getattr(getattr(window, "release_profile", None), "mode", "") == "tester":
        from rpg_vkr.deployment import tester_token

        return bool(
            getattr(window, "_tester_endpoint", window.release_profile.gateway)
            and tester_token(window)
        )
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


def require_world(window):
    """A connected writer cannot turn an unfinished hero into the legacy episode."""
    if window._legacy_controls or window._session.generated_world:
        return True
    from rpg_vkr.ui.adventure_panel import world_start_message

    message = world_start_message(window)
    window.narrator_status.setText(message)
    window.statusBar().showMessage(message)
    return False
