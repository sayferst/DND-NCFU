"""Explicit image-provider connection, two named models and separate protected credentials."""

import os

from PySide6.QtCore import QObject
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

from rpg_vkr.narrative.cloud import validate_api_key
from rpg_vkr.narrative.routerai import _data
from rpg_vkr.storage.artist_connection import ArtistPreferences
from rpg_vkr.storage.connection import load_secret, save_secret, windows_credentials_available
from rpg_vkr.ui.episode_panels import plain_label
from rpg_vkr.visuals.client import ImagesWorker
from rpg_vkr.visuals.policy import FLUX, RECRAFT, quote_model, rub

MODELS = {
    RECRAFT: ("Recraft V4.1 Flash", "Обычные предметы и материалы; только текст, без референсов."),
    FLUX: (
        "FLUX 3 Image Klein",
        "Персонажи, существа, уникальные вещи и сцены; референсы при поддержке API.",
    ),
}


def master_routerai_key(window):
    return (
        (window.cloud_key.text().strip() if window.ai_provider.currentData() == "routerai" else "")
        or os.environ.get("RPG_VKR_ROUTERAI_API_KEY", "").strip()
        or load_secret(window._credential_path)
    )


class ArtistPanel(QObject):
    def __init__(self, window, controller):
        super().__init__(window)
        self.window, self.controller = window, controller
        self.path = controller.settings_path.with_name("connection.json")
        self.credential_path = window._saves.directory.parent / "artist-credential.bin"
        self.preferences = ArtistPreferences.load(self.path)
        self._own_key = load_secret(self.credential_path) if self.preferences.remember_key else ""
        self._syncing = False
        self.closed = False
        self.catalog = None
        self.present = set()
        self._ticket = 0
        self._checking = None
        self._inflight = False
        self.worker = ImagesWorker(self)
        self.worker.finished.connect(self.checked)
        page = window.artist_page
        self.connection_status = plain_label("Ключ и модели Художника ещё не проверены.")
        page.addWidget(self.connection_status)
        self.operation_status = plain_label(controller.notice)
        page.addWidget(self.operation_status)

        connection = QGroupBox("1. Подключение Художника · RouterAI Images")
        form = QFormLayout(connection)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Адрес API:", plain_label("https://routerai.ru/api/v1/images"))
        self.shared_key = QCheckBox("Использовать ключ Мастера")
        self.shared_key.setChecked(self.preferences.shared_key)
        form.addRow(self.shared_key)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("API-ключ RouterAI для изображений, без Bearer")
        self.key_input.setAccessibleName("API-ключ Художника RouterAI")
        form.addRow("API-ключ:", self.key_input)
        self.key_source = plain_label()
        form.addRow(self.key_source)
        tools = QHBoxLayout()
        self.show_key = QCheckBox("Показать ключ")
        self.show_key.toggled.connect(
            lambda checked: self.key_input.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        tools.addWidget(self.show_key)
        self.save_key_button = QPushButton("Сохранить ключ Художника")
        self.save_key_button.clicked.connect(self.save_key)
        tools.addWidget(self.save_key_button)
        form.addRow(tools)
        self.remember_key = QCheckBox("Запоминать отдельный ключ на этом ПК · Windows")
        self.remember_key.setChecked(self.preferences.remember_key)
        form.addRow(self.remember_key)
        actions = QHBoxLayout()
        self.forget_key_button = QPushButton("Удалить сохранённый ключ Художника")
        self.forget_key_button.clicked.connect(self.forget_key)
        actions.addWidget(self.forget_key_button)
        master = QPushButton("Открыть Мастера")
        master.clicked.connect(lambda: window.open_section("Мастер"))
        actions.addWidget(master)
        form.addRow(actions)
        page.addWidget(connection)

        models = QGroupBox("2. Две модели изображений")
        layout = QVBoxLayout(models)
        layout.addWidget(
            plain_label(
                "Recraft — обычные предметы. FLUX — персонажи и сцены. "
                "При генерации модель выбирается автоматически по объекту и референсам; "
                "ниже можно быстро посмотреть её назначение и тариф."
            )
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти модель: Recraft или FLUX…")
        self.search.setAccessibleName("Поиск модели Художника")
        layout.addWidget(self.search)
        self.model_choice = QComboBox()
        self.model_choice.setMinimumContentsLength(16)
        self.model_choice.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.model_choice.setAccessibleName("Модель Художника · сведения и тариф")
        layout.addWidget(self.model_choice)
        self.model_id = QLineEdit()
        self.model_id.setReadOnly(True)
        self.model_id.setAccessibleName("ID модели изображений")
        layout.addWidget(self.model_id)
        self.model_details = plain_label()
        layout.addWidget(self.model_details)
        buttons = QHBoxLayout()
        self.catalog_button = QPushButton("Загрузить модели")
        self.catalog_button.clicked.connect(lambda: self.check("catalog"))
        buttons.addWidget(self.catalog_button)
        self.check_button = QPushButton("Проверить ключ и модели")
        self.check_button.clicked.connect(lambda: self.check("connection"))
        buttons.addWidget(self.check_button)
        layout.addLayout(buttons)
        self.cancel_check = QPushButton("Отменить проверку")
        self.cancel_check.setEnabled(False)
        self.cancel_check.clicked.connect(self.cancel_metadata)
        layout.addWidget(self.cancel_check)
        self.catalog_status = plain_label(
            "Показаны две утверждённые модели. Наличие и цена ещё не подтверждены каталогом. "
            "Загрузка моделей не требует ключа и не создаёт изображений."
        )
        layout.addWidget(self.catalog_status)
        page.addWidget(models)
        self.budget_toggle = QPushButton("Бюджет, разрешения и качество ▸")
        self.budget_toggle.setCheckable(True)
        page.addWidget(self.budget_toggle)
        budget = QWidget()
        self.budget_form = QFormLayout(budget)
        self.budget_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.budget_toggle.toggled.connect(budget.setVisible)
        page.addWidget(budget)
        budget.hide()
        page.addStretch()
        self.shared_key.toggled.connect(self.source_changed)
        self.key_input.textChanged.connect(self.key_edited)
        self.remember_key.toggled.connect(lambda _: self.persist())
        self.search.textChanged.connect(lambda _: self.populate_models())
        self.model_choice.activated.connect(lambda _: self.model_selected())
        window.cloud_key.textChanged.connect(lambda _: self.master_changed())
        window.ai_provider.currentIndexChanged.connect(lambda _: self.master_changed())
        self.sync_key()
        self.populate_models()
        shortcut = QPushButton("Открыть Художника: ключ и модели изображений…")
        shortcut.clicked.connect(lambda: window.open_section("Художник"))
        window.settings_form.addRow(shortcut)

    def effective_key(self):
        return (
            master_routerai_key(self.window)
            if self.shared_key.isChecked()
            else self.key_input.text().strip()
        )

    def persist(self):
        try:
            preferences = ArtistPreferences(
                self.shared_key.isChecked(),
                self.remember_key.isChecked(),
                self.model_choice.currentData() or self.preferences.selected_model,
            )
            preferences.save(self.path)
            self.preferences = preferences
            return True
        except (OSError, ValueError):
            self.connection_status.setText("Не удалось сохранить настройки Художника.")
            return False

    def sync_key(self):
        self._syncing = True
        shared = self.shared_key.isChecked()
        self.key_input.setText(master_routerai_key(self.window) if shared else self._own_key)
        self.key_input.setEnabled(not shared)
        self.show_key.setChecked(False)
        supported = windows_credentials_available()
        self.remember_key.setEnabled(not shared and supported)
        self.save_key_button.setEnabled(not shared and supported)
        self.forget_key_button.setEnabled(self.credential_path.exists())
        self.key_source.setText(
            "Сейчас используется ключ RouterAI из панели «Мастер». "
            "Для отдельного ключа снимите отметку выше."
            if shared
            else "Это отдельный ключ Художника. Ключ и модель Мастера не изменятся."
        )
        self._syncing = False

    def changed_credentials(self):
        # Public catalog loading is independent of credentials and can finish while typing.
        if self._checking is None or self._checking[1] != "catalog":
            self._ticket += 1
            self._checking = None
        self.connection_status.setText(
            "Ключ или его источник изменён. Проверьте подключение Художника."
        )
        if (self.controller.active or self.controller.queue) and not self.controller.cancelled:
            self.controller.cancel()

    def source_changed(self):
        self.sync_key()
        self.changed_credentials()
        self.persist()

    def key_edited(self):
        if not self._syncing and not self.shared_key.isChecked():
            self._own_key = self.key_input.text()
            self.changed_credentials()

    def master_changed(self):
        if self.shared_key.isChecked():
            self.sync_key()
            self.changed_credentials()

    def save_key(self):
        if self.shared_key.isChecked():
            self.connection_status.setText("Общий ключ сохраняется в панели «Мастер».")
            return False
        try:
            save_secret(self.credential_path, validate_api_key(self.effective_key()))
        except (ValueError, OSError):
            self.connection_status.setText(
                "Ключ Художника не сохранён. Проверьте ввод и защищённое хранилище Windows."
            )
            return False
        self.remember_key.setChecked(True)
        saved = self.persist()
        self.forget_key_button.setEnabled(True)
        self.connection_status.setText(
            "Последний ключ Художника сохранён зашифрованным. Платных запросов не было."
            + (" Но настройки не удалось сохранить." if not saved else "")
        )
        return saved

    def forget_key(self):
        try:
            self.credential_path.unlink(missing_ok=True)
        except OSError:
            self.connection_status.setText("Не удалось удалить зашифрованный ключ Художника.")
            return
        self.remember_key.setChecked(False)
        self.persist()
        self.forget_key_button.setEnabled(False)
        self.connection_status.setText(
            "Сохранённый ключ Художника удалён с диска. Поле текущего сеанса оставлено. "
            "Ключ Мастера и ключ в кабинете RouterAI не изменены."
        )

    def populate_models(self):
        current = self.model_choice.currentData() or self.preferences.selected_model
        query = self.search.text().strip().casefold()
        self.model_choice.blockSignals(True)
        self.model_choice.clear()
        for identity, (name, _) in MODELS.items():
            if query and query not in (identity + " " + name).casefold():
                continue
            state = (
                "не проверена"
                if self.catalog is None
                else "есть в каталоге"
                if identity in self.present
                else "не найдена"
            )
            self.model_choice.addItem(name + " · " + state, identity)
        index = self.model_choice.findData(current)
        self.model_choice.setCurrentIndex(max(0, index) if self.model_choice.count() else -1)
        self.model_choice.blockSignals(False)
        self.refresh_model_details()

    def model_selected(self):
        self.persist()
        self.refresh_model_details()

    def refresh_model_details(self):
        model = self.model_choice.currentData()
        self.model_id.setText(model or "")
        if not model:
            self.model_details.setText("Нет совпадений. Ищите Recraft или FLUX.")
            return
        name, role = MODELS[model]
        description = name + ": " + role
        if self.catalog is None:
            description += "\nАктуальный тариф ещё не загружен."
        else:
            size = "1K" if model == RECRAFT else self.controller.settings.portrait_size
            try:
                quote = quote_model(self.catalog, model, size)
                cap = (
                    self.controller.settings.economy_cap
                    if model == RECRAFT
                    else self.controller.settings.quality_cap
                )
                description += (
                    f"\nРазмер {quote.size_description}: полная цена {rub(quote.total)}; "
                    f"ваш порог {rub(cap)}. "
                    f"Референсы: до {quote.reference_limit if quote.supports_references else 0}."
                )
            except ValueError as error:
                description += "\nТариф/возможности не подтверждены: " + str(error)
        self.model_details.setText(description)

    def check(self, mode):
        if self._inflight or self.worker.busy or self.closed:
            return
        key = self.effective_key()
        if mode == "connection":
            try:
                validate_api_key(key)
            except ValueError as error:
                self.connection_status.setText(str(error))
                return
        self._ticket += 1
        ticket = self._ticket
        self._checking = (ticket, mode, key)
        self._inflight = True
        self.catalog_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.cancel_check.setEnabled(True)
        target = self.connection_status if mode == "connection" else self.catalog_status
        target.setText("Проверяем RouterAI… Только GET, без платной генерации.")
        self.worker.start(
            lambda transport: (
                ticket,
                transport.metadata(key) if mode == "connection" else transport.catalog(),
            )
        )

    def cancel_metadata(self):
        self._ticket += 1
        self._checking = None
        self.cancel_check.setEnabled(False)
        self.connection_status.setText("Проверка отменена; её поздний ответ не применяется.")

    def checked(self, result):
        self._inflight = False
        if self.closed:
            return
        self.catalog_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.cancel_check.setEnabled(False)
        pending, self._checking = self._checking, None
        if pending is None:
            return
        ticket, mode, key = pending
        if ticket != self._ticket or mode == "connection" and key != self.effective_key():
            return
        label = self.connection_status if mode == "connection" else self.catalog_status
        if "error" in result:
            label.setText(result["error"])
            return
        received_ticket, value = result["value"]
        if received_ticket != ticket:
            return
        if mode == "connection":
            allowance, catalog = value
        else:
            catalog = value
        rows = _data(catalog)
        if not isinstance(rows, list) or len(rows) > 10000:
            label.setText("Неизвестный формат каталога RouterAI. Платных запросов не было.")
            return
        self.catalog = catalog
        self.present = {
            row.get("id")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        self.populate_models()
        found = len(set(MODELS) & self.present)
        self.catalog_status.setText(
            f"В каталоге найдено утверждённых моделей: {found} из 2. "
            "Тариф и возможности показаны для выбранной модели; списаний нет."
        )
        if mode == "connection":
            self.connection_status.setText(
                f"Ключ Художника проверен. Остаток лимита: {allowance.remaining:.2f} ₽. "
                "Наличие ID не гарантирует генерацию: "
                "полный тариф и параметры проверяются отдельно."
            )
            if not self.shared_key.isChecked() and self.remember_key.isChecked():
                verified = self.connection_status.text()
                saved = self.save_key()
                self.connection_status.setText(
                    verified
                    + (
                        " Последний ключ сохранён зашифрованным."
                        if saved
                        else " Не удалось подтвердить сохранение ключа/настроек."
                    )
                )

    def show_budget(self):
        self.window.open_section("Художник")
        self.budget_toggle.setChecked(True)

    def close(self):
        self.closed = True
        self._ticket += 1
        self._checking = None
