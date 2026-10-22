"""One clearly labelled connection form; diagnostics do not obscure everyday controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def install_connection_layout(window, page):
    from rpg_vkr.ui.episode_panels import plain_label
    from rpg_vkr.ui.flash_settings import disconnect

    while page.count():
        item = page.takeAt(0)
        if item.widget():
            item.widget().hide()
    window.connection_status = plain_label("Не подключено · укажите ключ и выберите модель.")
    page.addWidget(window.connection_status)
    account = QGroupBox("1. Сервис и API-ключ")
    form = QFormLayout(account)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.addRow("Сервис:", window.ai_provider)
    window.ai_provider.setAccessibleName("Сервис облачного мастера")
    window.connection_endpoint = plain_label()
    form.addRow("Адрес API:", window.connection_endpoint)
    form.addRow("API-ключ:", window.cloud_key)
    window.cloud_key.setAccessibleName("API-ключ выбранного сервиса")
    window.show_api_key = QCheckBox("Показать ключ на экране")
    window.show_api_key.toggled.connect(
        lambda visible: window.cloud_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
    )
    window.key_tools_layout = QHBoxLayout()
    window.key_tools_layout.addWidget(window.show_api_key)
    form.addRow(window.key_tools_layout)
    window.connection_key_form = form
    window.connection_storage = QPushButton("Хранение ключа и сохранение настроек ▸")
    window.connection_storage.setCheckable(True)
    form.addRow(window.connection_storage)
    storage = QWidget()
    window.connection_options_layout = QFormLayout(storage)
    form.addRow(storage)
    window.connection_storage.toggled.connect(storage.setVisible)
    storage.hide()
    page.addWidget(account)

    models = QGroupBox("2. Модель текстового мастера")
    layout = QVBoxLayout(models)
    layout.addWidget(
        plain_label("Каталог RouterAI публичный: ключ нужен для проверки доступа и игры.")
    )
    layout.addWidget(window.routerai_catalog_button)
    window.model_search = QLineEdit()
    window.model_search.setPlaceholderText("Поиск в загруженном каталоге: deepseek, flash…")
    window.model_search.setAccessibleName("Поиск текстовой модели в каталоге")
    window.model_search.textChanged.connect(lambda _: filter_models(window))
    layout.addWidget(window.model_search)
    window.routerai_model_list.setMinimumContentsLength(20)
    window.routerai_model_list.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    window.routerai_model_list.setMaxVisibleItems(12)
    window.routerai_model_list.setAccessibleName("Текстовые модели RouterAI")
    layout.addWidget(window.routerai_model_list)
    window.catalog_status = plain_label("Каталог ещё не загружен. Можно указать ID модели вручную.")
    layout.addWidget(window.catalog_status)
    manual = QFormLayout()
    manual.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    manual.addRow("ID модели:", window.cloud_model)
    window.cloud_model.setAccessibleName("ID модели текстового мастера")
    layout.addLayout(manual)
    layout.addWidget(window.routerai_price)
    layout.addWidget(window.cloud_free_only)
    page.addWidget(models)

    activate = QGroupBox("3. Подключение")
    layout = QVBoxLayout(activate)
    layout.addWidget(window.cloud_allowed)
    layout.addWidget(window.cloud_notice)
    window.find_models_button.setText("Проверить ключ и подключить мастера")
    window.routerai_catalog_button.setText("Обновить каталог моделей RouterAI")
    layout.addWidget(window.find_models_button)
    row = QHBoxLayout()
    window.disconnect_master = QPushButton("Отключить мастера")
    window.disconnect_master.clicked.connect(lambda: disconnect(window))
    row.addWidget(window.disconnect_master)
    row.addWidget(window.cancel_narration_button)
    layout.addLayout(row)
    page.addWidget(activate)
    page.addWidget(window.narrator_status)

    window.connection_advanced = QPushButton("Диагностика и дополнительные параметры ▸")
    window.connection_advanced.setCheckable(True)
    page.addWidget(window.connection_advanced)
    details = QWidget()
    advanced = QVBoxLayout(details)
    for widget in (
        window.ai_chat,
        window.world_agent,
        window.prompt_notice,
        window.narrator_metrics,
        window.show_narrator_details,
        window.narrator_details,
        window.narrator_context,
    ):
        advanced.addWidget(widget)
        widget.show()
    window.narrator_details.setVisible(window.show_narrator_details.isChecked())
    window.narrator_context.setMinimumHeight(150)
    page.addWidget(details)
    window.connection_advanced.toggled.connect(details.setVisible)
    details.hide()
    for widget in (
        window.ai_provider,
        window.find_models_button,
        window.cancel_narration_button,
    ):
        widget.show()
    page.addStretch()
    # The legacy/internal model and mode widgets remain functional but are not extra selectors.
    for widget in (
        window.enable_local_narrator,
        window.local_model,
        window.auto_narration,
        window.director_mode,
        window.narrate_button,
    ):
        widget.hide()
    window.show_api_key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    refresh_connection_layout(window)


def filter_models(window):
    query = window.model_search.text().strip().casefold() if hasattr(window, "model_search") else ""
    current = window.cloud_model.text().strip()
    combo = window.routerai_model_list
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("Выберите текстовую модель или введите её ID ниже", "")
    count = 0
    for quote in window._routerai_quotes.values():
        if query and query not in quote.id.casefold():
            continue
        combo.addItem(quote.label, quote.id)
        count += 1
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)
    if hasattr(window, "model_search"):
        window.model_search.setToolTip(f"Показано моделей: {count}")


def refresh_connection_layout(window):
    if not hasattr(window, "connection_status"):
        return
    from rpg_vkr.narrative.cloud import ENDPOINTS

    provider = window.ai_provider.currentData()
    router = provider == "routerai"
    window.connection_endpoint.setText(ENDPOINTS.get(provider, ""))
    window.model_search.setVisible(router)
    window.local_model.hide()
    window.enable_local_narrator.hide()
    window.find_models_button.setText(
        "Проверить ключ и подключить мастера" if router else "Применить облачное подключение"
    )
    window.disconnect_master.setEnabled(
        window.enable_local_narrator.isChecked() or getattr(window, "_flash_pending", False)
    )
    if hasattr(window, "save_api_key"):
        from rpg_vkr.storage.connection import windows_credentials_available

        supported = router and windows_credentials_available()
        window.save_api_key.setEnabled(supported)
        window.remember_key.setEnabled(supported)
