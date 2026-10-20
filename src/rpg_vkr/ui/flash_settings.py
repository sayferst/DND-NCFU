"""One-click Flash convenience using existing RouterAI metadata, limits and client."""

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

from rpg_vkr.storage.connection import (
    FLASH_MODEL,
    ConnectionPreferences,
    load_secret,
    save_secret,
    windows_credentials_available,
)


def install_flash_settings(window):
    form = window.settings_form
    window._connection_path = window._saves.directory.parent / "ai-connection.json"
    window._credential_path = window._saves.directory.parent / "routerai-credential.bin"
    window._flash_preferences = ConnectionPreferences.load(window._connection_path)
    window._flash_pending = False
    window._flash_verified = False
    window._updating_flash = True
    window.flash_enabled = QCheckBox("Включить ИИ-мастера DeepSeek Flash")
    form.addRow(window.flash_enabled)
    window.flash_status = QLabel("Выключен")
    window.flash_status.setWordWrap(True)
    form.addRow("Подключение:", window.flash_status)
    window.flash_configure = QPushButton("Параметры подключения…")
    window.flash_configure.clicked.connect(lambda: configure(window))
    form.addRow(window.flash_configure)
    window.remember_key = QCheckBox("Запомнить ключ на этом ПК · защищённое хранилище Windows")
    window.remember_key.setEnabled(windows_credentials_available())
    window.remember_key.setToolTip(
        "DPAPI текущего пользователя Windows. На других ОС используйте переменную окружения."
    )
    form.addRow(window.remember_key)
    window.connection_save = QPushButton("Сохранить подключение")
    window.connection_save.clicked.connect(lambda: save_connection(window))
    form.addRow(window.connection_save)
    link = QLabel('<a href="https://routerai.ru/settings/keys">Получить ключ на RouterAI</a>')
    link.setOpenExternalLinks(True)
    form.addRow(link)
    note = QLabel(
        "Проверка подключения не генерирует рассказ. Перед генерацией сохраняется "
        "проверка месячного лимита до 2000 ₽. Пополнения не выполняются."
    )
    note.setWordWrap(True)
    form.addRow(note)
    for widget in (
        window.flash_enabled,
        window.flash_status,
        window.flash_configure,
        window.remember_key,
        window.connection_save,
        link,
        note,
    ):
        widget.setFont(window.font())
    window.flash_enabled.toggled.connect(lambda checked: toggle_flash(window, checked))
    window.routerai_catalog.key_ready.connect(lambda allowance: key_verified(window, allowance))
    window.routerai_catalog.catalog_ready.connect(lambda quotes: models_verified(window, quotes))
    window.routerai_catalog.failed.connect(lambda message: connection_failed(window, message))
    window.ollama.failed.connect(lambda message: generation_status(window, message))
    window.cloud_key.textEdited.connect(lambda _: invalidate(window))
    window.cloud_model.textEdited.connect(lambda _: invalidate(window))
    window.routerai_model_list.activated.connect(lambda _: invalidate(window))
    window.ai_provider.currentIndexChanged.connect(lambda _: invalidate(window))
    window.cloud_allowed.toggled.connect(lambda allowed: None if allowed else invalidate(window))
    preferences = window._flash_preferences
    if preferences.provider != "local":
        window.ai_provider.setCurrentIndex(window.ai_provider.findData(preferences.provider))
        window.cloud_model.setText(preferences.model)
        window.cloud_allowed.setChecked(preferences.consent)
        if preferences.provider == "routerai":
            stored = load_secret(window._credential_path)
            window.cloud_key.setText(stored)
            window.remember_key.setChecked(bool(stored))
    window._updating_flash = False
    # Preference is restored, but no model request is issued. Metadata checks require key + consent.
    if preferences.enabled and preferences.provider == "routerai":
        QTimer.singleShot(0, lambda: restore_enabled(window))


def restore_enabled(window):
    if getattr(window, "_closing", False):
        return
    key = window.cloud_key.text().strip() or os.environ.get("RPG_VKR_ROUTERAI_API_KEY", "")
    if not key or not window.cloud_allowed.isChecked():
        window.flash_status.setText("Не настроен · нет ключа или согласия. Настройте подключение.")
        return
    window.flash_enabled.setChecked(True)


def configure(window):
    window.open_section("Рассказчик")
    if window.ai_provider.currentData() != "routerai":
        window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
    window.cloud_key.setFocus()


def set_checked(window, checked):
    window.flash_enabled.blockSignals(True)
    window.flash_enabled.setChecked(checked)
    window.flash_enabled.blockSignals(False)


def save_preferences(window, enabled):
    preferences = ConnectionPreferences(
        window.ai_provider.currentData(),
        window.cloud_model.text().strip(),
        enabled,
        window.cloud_allowed.isChecked(),
    )
    try:
        preferences.save(window._connection_path)
    except (OSError, ValueError):
        window.flash_status.setText("Не удалось сохранить настройки подключения.")
    else:
        window._flash_preferences = preferences


def save_connection(window):
    if window.ai_provider.currentData() != "routerai":
        window.flash_status.setText("Для Flash выберите RouterAI в параметрах подключения.")
        return
    key = window.cloud_key.text().strip() or os.environ.get("RPG_VKR_ROUTERAI_API_KEY", "")
    try:
        if window.remember_key.isChecked():
            save_secret(window._credential_path, key)
        elif window._credential_path.exists():
            window._credential_path.unlink()
    except (OSError, ValueError):
        window.flash_status.setText(
            "Ключ не сохранён. Используйте переменную окружения или ввод на время сеанса."
        )
        return
    save_preferences(window, window.flash_enabled.isChecked())
    window.flash_status.setText("Настройки сохранены. Включите Flash для проверки подключения.")


def toggle_flash(window, checked):
    from rpg_vkr.ui.narrator_panel import cancel_narration

    cancel_narration(window)
    window.routerai_catalog.cancel()
    window._flash_pending = False
    window._flash_verified = False
    if not checked:
        window.enable_local_narrator.setChecked(False)
        window.flash_status.setText("Выключен")
        save_preferences(window, False)
        return
    key = window.cloud_key.text().strip() if window.ai_provider.currentData() == "routerai" else ""
    key = (
        key
        or os.environ.get("RPG_VKR_ROUTERAI_API_KEY", "")
        or load_secret(window._credential_path)
    )
    consent = (
        window.cloud_allowed.isChecked()
        if window.ai_provider.currentData() == "routerai"
        else window._flash_preferences.consent
    )
    window._updating_flash = True
    window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
    window.cloud_model.setText(FLASH_MODEL)
    window.cloud_key.setText(key)
    window.cloud_allowed.setChecked(consent)
    window._updating_flash = False
    window.enable_local_narrator.setChecked(False)
    if not key or not consent:
        set_checked(window, False)
        window.flash_status.setText("Не настроен · укажите ключ и разрешите отправку сцены.")
        configure(window)
        return
    window._flash_pending = True
    window.flash_status.setText("Проверяется ключ, лимит и доступность Flash…")
    window.routerai_catalog.check_key(key)


def key_verified(window, allowance):
    if window._flash_pending and window.flash_enabled.isChecked():
        window.routerai_catalog.list_models()


def models_verified(window, quotes):
    if not window._flash_pending or not window.flash_enabled.isChecked():
        return
    if not any(q.id == FLASH_MODEL for q in quotes):
        connection_failed(
            window, "Модель Flash отсутствует в актуальном каталоге. Другая модель не выбрана."
        )
        return
    from rpg_vkr.ui.narrator_panel import prepare_model

    if not prepare_model(window):
        connection_failed(window, "Не удалось применить подключение.")
        return
    window._flash_pending = False
    window._flash_verified = True
    window.ai_chat.setChecked(True)
    window.world_agent.setChecked(True)
    window.enable_local_narrator.setChecked(True)
    window.flash_status.setText(
        "Подключён · DeepSeek Flash. Запросы — только при игровых действиях."
    )
    save_preferences(window, True)


def connection_failed(window, message):
    if not window._flash_pending:
        return
    window._flash_pending = False
    window._flash_verified = False
    window.enable_local_narrator.setChecked(False)
    set_checked(window, False)
    save_preferences(window, False)
    generation_status(window, message, force=True)


def generation_status(window, message, force=False):
    if not force and not window.flash_enabled.isChecked():
        return
    limited = any(
        word in message.casefold() for word in ("исчерпан", "недостаточно баланса", "402", "429")
    )
    label = (
        "Лимит исчерпан"
        if limited
        else "Не настроен"
        if any(word in message.casefold() for word in ("401", "ключ", "модель", "подключение"))
        else "Нет соединения"
    )
    window.flash_status.setText(label + " · " + message[:240])


def invalidate(window):
    if window._updating_flash:
        return
    window._flash_verified = False
    if window.flash_enabled.isChecked():
        window.routerai_catalog.cancel()
        window._flash_pending = False
        window.enable_local_narrator.setChecked(False)
        set_checked(window, False)
        window.flash_status.setText(
            "Не настроен · параметры изменены; включите Flash для повторной проверки."
        )
        save_preferences(window, False)
