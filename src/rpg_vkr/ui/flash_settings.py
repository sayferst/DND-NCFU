"""Shared connection lifecycle; Flash is a shortcut, never a replacement for the chosen model."""

import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

from rpg_vkr.storage.connection import (
    FLASH_MODEL,
    ConnectionPreferences,
    load_secret,
    save_secret,
    windows_credentials_available,
)


def connection_message(window, text):
    window.flash_status.setText(text)
    if hasattr(window, "connection_status"):
        window.connection_status.setText(text)


def install_flash_settings(window):
    form = window.settings_form if window._legacy_controls else window.connection_options_layout
    window._connection_path = window._saves.directory.parent / "ai-connection.json"
    window._credential_path = window._saves.directory.parent / "routerai-credential.bin"
    window._flash_preferences = ConnectionPreferences.load(window._connection_path)
    window._flash_pending = False
    window._flash_verified = False
    window._connection_mode = ""
    window._connection_key_ok = False
    window._updating_flash = True
    window.flash_enabled = QCheckBox("Быстро подключить DeepSeek Flash через RouterAI")
    form.addRow(window.flash_enabled)
    window.flash_status = QLabel("Выключен")
    window.flash_status.setWordWrap(True)
    form.addRow("Мастер:", window.flash_status)
    window.flash_configure = QPushButton("Настроить API-ключ и выбрать модель…")
    window.flash_configure.clicked.connect(lambda: configure(window))
    window.settings_form.addRow(window.flash_configure)
    options = getattr(window, "connection_options_layout", form)
    window.remember_key = QCheckBox("Запоминать последний ключ на этом ПК · Windows")
    window.remember_key.setEnabled(windows_credentials_available())
    window.remember_key.setToolTip(
        "DPAPI текущего пользователя. Без этой отметки ключ действует только в этом сеансе "
        "или берётся из переменной окружения; открытого файла с ключом нет."
    )
    getattr(window, "connection_key_form", options).addRow(window.remember_key)
    window.save_api_key = QPushButton("Сохранить последний API-ключ")
    window.save_api_key.setEnabled(windows_credentials_available())
    window.save_api_key.setToolTip("Зашифровать ключ RouterAI для текущего пользователя Windows.")
    window.save_api_key.clicked.connect(lambda: save_last_key(window))
    if hasattr(window, "key_tools_layout"):
        window.key_tools_layout.addWidget(window.save_api_key)
    else:
        options.addRow(window.save_api_key)
    window.connection_save = QPushButton("Сохранить настройки и выбранный способ хранения ключа")
    window.connection_save.clicked.connect(lambda: save_connection(window))
    options.addRow(window.connection_save)
    window.flash_link = QLabel()
    style_connection_link(window)
    window.flash_link.setOpenExternalLinks(True)
    options.addRow(window.flash_link)
    note = QLabel(
        "Проверка ключа и каталог — бесплатные GET-запросы. Рассказы оплачиваются "
        "по тарифу модели; у RouterAI-ключа нужен месячный лимит до 2000 ₽."
    )
    note.setWordWrap(True)
    form.addRow(note)
    window.flash_enabled.toggled.connect(lambda checked: toggle_flash(window, checked))
    window.routerai_key_client.key_ready.connect(lambda allowance: key_verified(window, allowance))
    window.routerai_key_client.failed.connect(lambda message: connection_failed(window, message))
    window.routerai_catalog.catalog_ready.connect(lambda quotes: models_verified(window, quotes))
    window.routerai_catalog.failed.connect(
        lambda message: catalog_connection_failed(window, message)
    )
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
    if not window._legacy_controls and preferences.provider == "local":
        window.ai_provider.setCurrentIndex(window.ai_provider.findData("routerai"))
        stored = load_secret(window._credential_path)
        window.cloud_key.setText(stored)
        window.remember_key.setChecked(bool(stored))
    window._updating_flash = False
    if preferences.enabled and preferences.provider == "routerai":
        QTimer.singleShot(0, lambda: restore_enabled(window))


def style_connection_link(window):
    color = window.palette().color(QPalette.ColorRole.Link).name()
    window.flash_link.setText(
        f'<a style="color:{color}" href="https://routerai.ru/settings/keys">'
        "Получить или настроить ключ RouterAI</a>"
    )


def effective_key(window):
    variable = (
        "RPG_VKR_ROUTERAI_API_KEY"
        if window.ai_provider.currentData() == "routerai"
        else "RPG_VKR_LLM_API_KEY"
    )
    return window.cloud_key.text().strip() or os.environ.get(variable, "").strip()


def snapshot(window):
    return (
        window.ai_provider.currentData(),
        window.cloud_model.text().strip(),
        effective_key(window),
        window.cloud_allowed.isChecked(),
    )


def restore_enabled(window):
    if getattr(window, "_closing", False):
        return
    if not effective_key(window) or not window.cloud_allowed.isChecked():
        connection_message(window, "Не настроен · нет ключа или согласия. Настройте подключение.")
        return
    if window.cloud_model.text().strip() == FLASH_MODEL:
        window.flash_enabled.setChecked(True)
    else:
        connect_selected(window)


def configure(window):
    window.open_section("Рассказчик" if window._legacy_controls else "Мастер")
    # Opening the form must not replace a provider, erase its key or change the model.
    window.cloud_key.setFocus()


def set_checked(window, checked):
    window.flash_enabled.blockSignals(True)
    window.flash_enabled.setChecked(checked)
    window.flash_enabled.blockSignals(False)


def save_preferences(window, enabled):
    try:
        preferences = ConnectionPreferences(
            window.ai_provider.currentData(),
            window.cloud_model.text().strip(),
            enabled,
            window.cloud_allowed.isChecked(),
        )
        preferences.save(window._connection_path)
    except (OSError, ValueError):
        connection_message(
            window, "Не удалось сохранить настройки: проверьте ID модели и папку данных."
        )
        return False
    else:
        window._flash_preferences = preferences
        return True


def store_key_choice(window):
    if window.ai_provider.currentData() != "routerai":
        return True
    try:
        if window.remember_key.isChecked():
            from rpg_vkr.narrative.cloud import validate_api_key

            save_secret(window._credential_path, validate_api_key(effective_key(window)))
        elif window._credential_path.exists():
            window._credential_path.unlink()
    except (OSError, ValueError):
        return False
    return True


def save_last_key(window):
    from rpg_vkr.narrative.cloud import validate_api_key

    if window.ai_provider.currentData() != "routerai":
        connection_message(window, "Защищённое сохранение здесь доступно для ключа RouterAI.")
        return
    try:
        key = validate_api_key(window.cloud_key.text().strip())
        save_secret(window._credential_path, key)
    except (OSError, ValueError):
        connection_message(
            window, "Ключ не сохранён. Проверьте поле ключа и доступ к хранилищу Windows."
        )
        return
    window.remember_key.setChecked(True)
    preferences_saved = save_preferences(window, window.enable_local_narrator.isChecked())
    connection_message(
        window,
        "Последний API-ключ сохранён в зашифрованном виде и подставится при следующем запуске. "
        "Это не проверка ключа и не платный запрос."
        + (
            " Проверьте также ID модели: его настройки не сохранились."
            if not preferences_saved
            else ""
        ),
    )


def save_connection(window):
    if not save_preferences(window, window.enable_local_narrator.isChecked()):
        return
    stored = store_key_choice(window)
    connection_message(
        window,
        "Настройки сохранены. Для проверки нажмите «Подключить мастера»."
        if stored
        else "Настройки сохранены, ключ не записан. Он доступен только в текущем сеансе.",
    )


def cancel_connection(window):
    window.routerai_key_client.cancel()
    window._flash_pending = False
    window._connection_key_ok = False
    window._connection_snapshot = None
    window._flash_verified = False
    set_checked(window, False)
    connection_message(window, "Проверка подключения отменена. Платных запросов не было.")


def disconnect(window):
    from rpg_vkr.ui.narrator_panel import cancel_narration, refresh_narrator_panels

    cancel_narration(window)
    window.enable_local_narrator.setChecked(False)
    window._flash_verified = False
    set_checked(window, False)
    window.ollama.use_local()  # Drop the applied profile/key, without starting a local model.
    save_preferences(window, False)
    connection_message(window, "Выключен · сохранения и ключ не удалены.")
    refresh_narrator_panels(window)


def toggle_flash(window, checked):
    if not checked:
        disconnect(window)
        return
    key = (
        (effective_key(window) if window.ai_provider.currentData() == "routerai" else "")
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
    start_connection(window, "flash")


def connect_selected(window):
    start_connection(window, "selected")


def start_connection(window, mode):
    from rpg_vkr.narrative.cloud import CloudProfile
    from rpg_vkr.ui.narrator_panel import cancel_narration, refresh_narrator_panels

    cancel_narration(window)
    window.enable_local_narrator.setChecked(False)
    window._flash_verified = False
    window._connection_mode = mode
    current = snapshot(window)
    if not current[3]:
        set_checked(window, False)
        connection_message(window, "Не настроен · разрешите отправку сцены облачному мастеру.")
        return
    try:
        CloudProfile(current[0], current[1], current[2])
    except ValueError as error:
        set_checked(window, False)
        connection_message(window, "Не настроен · " + str(error))
        return
    if current[0] != "routerai":
        complete_connection(window)
        return
    window._connection_snapshot = current
    window._connection_key_ok = False
    window._flash_pending = True
    connection_message(
        window, "Проверяется ключ RouterAI и его месячный лимит… Платных запросов нет."
    )
    refresh_narrator_panels(window)
    window.routerai_key_client.check_key(current[2])


def key_verified(window, allowance):
    if not window._flash_pending:
        return
    if snapshot(window) != window._connection_snapshot:
        cancel_connection(window)
        return
    window._connection_key_ok = True
    window._connection_allowance = allowance
    if window._connection_mode == "flash":
        connection_message(window, "Ключ проверен. Проверяется наличие DeepSeek Flash в каталоге…")
        window.routerai_catalog.list_models()
    else:
        complete_connection(window)


def models_verified(window, quotes):
    if (
        not window._flash_pending
        or window._connection_mode != "flash"
        or not window._connection_key_ok
    ):
        return
    if snapshot(window) != window._connection_snapshot:
        cancel_connection(window)
        return
    if not any(q.id == FLASH_MODEL for q in quotes):
        connection_failed(
            window, "Модель Flash отсутствует в актуальном каталоге. Другая модель не выбрана."
        )
        return
    complete_connection(window)


def complete_connection(window):
    from rpg_vkr.ui.narrator_panel import prepare_model, refresh_narrator_panels

    window._flash_pending = False
    if not prepare_model(window):
        set_checked(window, False)
        connection_message(window, "Не настроен · " + window.narrator_status.text())
        refresh_narrator_panels(window)
        return
    window._connection_snapshot = None
    window._flash_verified = (
        window.ai_provider.currentData() == "routerai"
        and window.cloud_model.text().strip() == FLASH_MODEL
    )
    set_checked(window, window._flash_verified)
    window.ai_chat.setChecked(True)
    window.world_agent.setChecked(True)
    window.enable_local_narrator.setChecked(True)
    stored = store_key_choice(window)
    save_preferences(window, True)
    model = window.cloud_model.text().strip()
    if window.ai_provider.currentData() == "routerai":
        allowance = window._connection_allowance
        text = f"Подключён · {model}. Ключ проверен; остаток лимита {allowance.remaining:.2f} ₽."
        if model not in window._routerai_quotes:
            text += " Доступность ID модели не проверена: обновите каталог или отправьте реплику."
    else:
        text = f"Профиль применён · {model}. Авторизация проверится с первым игровым запросом."
    if not stored:
        text += " Ключ не сохранён на диск, используется только в этом сеансе."
    connection_message(window, text)
    window.narrator_status.setText(
        "Настройки применены. Вернитесь к игре; платных запросов пока не было."
    )
    refresh_narrator_panels(window)


def catalog_connection_failed(window, message):
    if window._flash_pending and window._connection_mode == "flash":
        connection_failed(window, message)


def connection_failed(window, message):
    if not window._flash_pending:
        return
    window._flash_pending = False
    window._connection_snapshot = None
    window._connection_key_ok = False
    window._flash_verified = False
    window.enable_local_narrator.setChecked(False)
    set_checked(window, False)
    save_preferences(window, False)
    generation_status(window, message, force=True)
    from rpg_vkr.ui.narrator_panel import refresh_narrator_panels

    refresh_narrator_panels(window)


def generation_status(window, message, force=False):
    if not force and not (
        window.flash_enabled.isChecked() or window.enable_local_narrator.isChecked()
    ):
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
    connection_message(window, label + " · " + message[:400])


def invalidate(window):
    if window._updating_flash:
        return
    was_active = window._flash_pending or window.enable_local_narrator.isChecked()
    window._flash_verified = False
    if window._flash_pending:
        cancel_connection(window)
    if was_active or window.flash_enabled.isChecked():
        window.enable_local_narrator.setChecked(False)
        window.ollama.use_local()
        set_checked(window, False)
        connection_message(window, "Не настроен · параметры изменены; подключите мастера повторно.")
        save_preferences(window, False)
