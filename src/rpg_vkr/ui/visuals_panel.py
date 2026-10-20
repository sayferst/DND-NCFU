"""Consent-driven image queue and viewer. Public snapshots only; no game mutations."""

import base64
import os
from collections import deque

from PySide6.QtCore import QLockFile, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.storage.connection import load_secret
from rpg_vkr.visuals.client import ImageError, ImagesWorker
from rpg_vkr.visuals.context import entity_target, make_prompt, reference_candidates, scene_target
from rpg_vkr.visuals.policy import (
    FLUX,
    RECRAFT,
    SIZES,
    VisualSettings,
    payload,
    quote_model,
    route,
    rub,
)
from rpg_vkr.visuals.registry import VisualRegistry


class VisualController(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        root = window._saves.directory.parent / "visuals"
        root.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(root / "generation.lock"))
        self.locked = self.lock.tryLock(0)
        self.registry = VisualRegistry(root, recover=self.locked)
        self.settings_path = root / "settings.json"
        self.settings = VisualSettings.load(self.settings_path)
        self.queue = deque()
        self.active = None
        self.stage = ""
        self.cancelled = False
        self.closed = False
        self.worker = ImagesWorker(self)
        self.worker.finished.connect(self.finished)
        self.notice = (
            "Изображения создаются только по явному запросу. Месячный бюджет по умолчанию0₽."
        )
        self.install_settings()

    def status(self, text):
        self.notice = text
        self.label.setText(text)
        self.window.statusBar().showMessage(text, 12000)
        self.changed.emit()

    def key(self):
        window = self.window
        return (
            (
                window.cloud_key.text().strip()
                if window.ai_provider.currentData() == "routerai"
                else ""
            )
            or os.environ.get("RPG_VKR_ROUTERAI_API_KEY", "")
            or load_secret(window._credential_path)
        )

    def install_settings(self):
        form = self.window.settings_form
        title = QLabel("Визуальная память · RouterAI Images")
        title.setProperty("heading", True)
        form.addRow(title)
        self.consent = QCheckBox("Разрешить отправку публичных описаний и референсов в RouterAI")
        self.consent.setChecked(self.settings.consent)
        form.addRow(self.consent)

        def money(value, maximum):
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(0, maximum)
            spin.setValue(value / 1000000)
            spin.setSuffix(" ₽")
            return spin

        self.monthly = money(self.settings.monthly_micros, 2000)
        self.economy = money(self.settings.economy_cap, 0.85)
        self.quality = money(self.settings.quality_cap, 5)
        form.addRow("Месячный бюджет изображений:", self.monthly)
        form.addRow("Порог Recraft:", self.economy)
        form.addRow("Порог FLUX:", self.quality)
        self.portrait = QComboBox()
        self.portrait.addItems(SIZES)
        self.portrait.setCurrentText(self.settings.portrait_size)
        self.scene_size = QComboBox()
        self.scene_size.addItems(SIZES)
        self.scene_size.setCurrentText(self.settings.scene_size)
        form.addRow("Разрешение портретов:", self.portrait)
        form.addRow("Разрешение сцен:", self.scene_size)
        self.confirm = QCheckBox("Подтверждать каждый платный запрос")
        self.confirm.setChecked(self.settings.confirm)
        form.addRow(self.confirm)
        save = QPushButton("Сохранить бюджет и настройки изображений")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        form.addRow(self.totals)
        self.label = QLabel(self.notice)
        self.label.setWordWrap(True)
        form.addRow(self.label)
        self.cancel_button = QPushButton("Отменить очередь / ожидание изображения")
        self.cancel_button.clicked.connect(self.cancel)
        form.addRow(self.cancel_button)
        self.ledger = QListWidget()
        self.ledger.setMaximumHeight(160)
        form.addRow(self.ledger)
        reconcile = QPushButton("Сверить неопределённый расход с кабинетом RouterAI")
        reconcile.clicked.connect(self.reconcile)
        form.addRow(reconcile)
        for control in (
            self.consent,
            self.monthly,
            self.economy,
            self.quality,
            self.portrait,
            self.scene_size,
            self.confirm,
            self.label,
            self.totals,
            self.ledger,
            save,
            reconcile,
        ):
            control.setFont(self.window.font())
        self.refresh_totals()

    def save_settings(self):
        try:
            settings = VisualSettings(
                round(self.monthly.value() * 1000000),
                round(self.economy.value() * 1000000),
                round(self.quality.value() * 1000000),
                self.portrait.currentText(),
                self.scene_size.currentText(),
                self.confirm.isChecked(),
                self.consent.isChecked(),
            )
            if (
                settings.monthly_micros
                and settings != self.settings
                and not self.ask(
                    "Бюджет изображений",
                    f"Разрешить выбранные настройки? Месячный предел "
                    f"{rub(settings.monthly_micros)}. Текстовый мастер расходуется отдельно. "
                    "Это не пополнение счёта. Автогенерация и автоматические повторы выключены.",
                )
            ):
                return
            settings.save(self.settings_path)
            self.settings = settings
            self.status("Настройки изображений сохранены. Генерация не запускалась.")
        except (ValueError, OSError) as error:
            self.status(str(error))

    def ask(self, title, message):
        return (
            QMessageBox.question(
                self.window,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def refresh_totals(self):
        totals = self.registry.totals()
        self.totals.setText(
            f"Подтверждено API: {rub(totals['actual'])}; "
            f"учтено с резервами: {rub(totals['committed'])} / "
            f"{rub(self.settings.monthly_micros)}; "
            f"результатов с неизвестной суммой: {totals['unknown']}."
        )
        self.ledger.clear()
        for row in self.registry.ledger()[:100]:
            text = f"{row['model']} · {row['status']} · "
            text += (
                rub(row["actual_micros"])
                if row["actual_micros"] is not None
                else ("факт неизвестен, резерв " + rub(row["expected_micros"]))
            )
            self.ledger.addItem(text)
            self.ledger.item(self.ledger.count() - 1).setData(Qt.ItemDataRole.UserRole, row["id"])

    def reconcile(self):
        item = self.ledger.currentItem()
        if not item:
            return
        identity = item.data(Qt.ItemDataRole.UserRole)
        row = next((r for r in self.registry.ledger() if r["id"] == identity), None)
        if not row or row["status"] != "uncertain":
            self.status("Выберите запрос с неопределённым результатом (uncertain).")
            return
        value, ok = QInputDialog.getDouble(
            self.window,
            "Сверка расхода",
            "После проверки кабинета введите фактически списанную сумму, ₽. "
            "0 — только если списания точно не было. Повтор запроса не выполняется.",
            row["expected_micros"] / 1000000,
            0,
            1000000,
            4,
        )
        if ok:
            self.registry.reconcile(identity, round(value * 1000000))
            self.refresh_totals()
            self.status("Расход отмечен по ручной сверке. Новый запрос требует отдельной команды.")

    def request_entry(self, entry, *, regenerate=False, shared=None):
        try:
            target = (
                scene_target(self.window._session, event=entry)
                if entry.category == "events"
                else (entity_target(self.window._session, entry, shared=shared))
            )
            return self.request(target, regenerate=regenerate)
        except (ValueError, OSError) as error:
            self.status(str(error))

    def request_scene(self):
        try:
            return self.request(scene_target(self.window._session))
        except ValueError as error:
            self.status(str(error))

    def request(self, target, *, regenerate=False):
        cached = self.registry.latest_for(target.campaign, target.entity)
        if not cached:
            shared = self.registry.versions(target.campaign, target.subject)
            if shared:
                self.registry.bind(target.campaign, target.entity, target.subject)
                cached = shared[0]
        if cached and not regenerate:
            self.status("Изображение уже сохранено. Открытие не расходует деньги.")
            self.view(target.campaign, target.entity)
            return True
        if not self.locked:
            self.status("Генерация занята другим экземпляром игры. Просмотр кэша доступен.")
            return
        if not self.settings.consent or self.settings.monthly_micros <= 0:
            self.status(
                "В настройках изображений разрешите передачу данных и задайте месячный бюджет."
            )
            return
        if not self.key():
            self.status("Нужен действительный ключ RouterAI в параметрах подключения.")
            return
        pending = [self.active] if self.active else []
        if any(
            t.campaign == target.campaign and t.subject == target.subject
            for t in pending + list(self.queue)
        ):
            self.status("Этот образ уже в очереди; второй платный запрос не создан.")
            return
        if len(self.queue) >= 8:
            self.status("Очередь заполнена (8). Дождитесь завершения или отмените ожидание.")
            return
        self.queue.append(target)
        self.pump()
        return True

    def pump(self):
        if self.closed or self.active or self.worker.busy or not self.queue:
            return
        self.active = self.queue.popleft()
        self.cancelled = False
        self.stage = "metadata"
        self.status("Проверяются актуальные тарифы изображений и лимит ключа…")
        key = self.key()
        self._key = key
        self.worker.start(lambda transport: transport.metadata(key))

    def cancel(self):
        self.queue.clear()
        self.cancelled = True
        self.status(
            "Очередь отменена. Уже отправленный платный запрос не повторяется: "
            "его результат будет сохранён, если сервер ответит. "
            "Отмена ожидания не означает возврат денег."
        )

    def finished(self, result):
        if self.closed:
            return
        if self.stage == "metadata":
            if self.cancelled:
                self.active = None
                self.pump()
                return
            if "error" in result:
                self.status(result["error"])
                self.active = None
                self.pump()
                return
            try:
                allowance, catalog = result["value"]
                self.prepare_paid(allowance, catalog)
            except (ValueError, OSError) as error:
                self.status(str(error))
                self.active = None
                self.pump()
            return
        self.active = None
        self._key = ""
        if "error" in result:
            self.status(result["error"])
        else:
            self.status(
                "Изображение сохранено локально. "
                + ("Ожидание было отменено; повтор не выполнен." if self.cancelled else "")
            )
        self.refresh_totals()
        self.changed.emit()
        self.pump()

    def prepare_paid(self, allowance, catalog):
        from rpg_vkr.storage.campaigns import CampaignRepository

        target = self.active
        if not self.settings.consent or self.cancelled or self.closed or self.key() != self._key:
            raise ValueError("Подключение или согласие изменилось; платный запрос не отправлен.")
        if CampaignRepository.identity(self.window._session) != target.campaign:
            raise ValueError("Кампания сменилась. Неотправленная генерация отменена.")
        candidates = reference_candidates(self.registry, target)
        # Reuse a previous version of the same identity for regeneration, too.
        previous = self.registry.latest_for(target.campaign, target.entity)
        if previous and previous["id"] not in {a["id"] for a in candidates}:
            candidates.insert(0, previous | {"caption": target.title})
        model = route(target.category, target.common, bool(candidates))
        size = (
            self.settings.scene_size if target.category == "events" else self.settings.portrait_size
        )
        if model == RECRAFT:
            size = "1K"
        quote = quote_model(catalog, model, size, 1 if candidates else 0)
        refs = candidates[: quote.reference_limit] if quote.supports_references else []
        if quote.total > round(allowance.remaining * 1000000):
            raise ValueError("Лимита ключа RouterAI недостаточно для полной цены запроса.")
        if quote.total > self.settings.quality_cap and model == FLUX:
            raise ValueError("Цена FLUX выше разрешённого порога. Запрос не отправлен.")
        beyond = model == RECRAFT and quote.total > self.settings.economy_cap
        text = (
            f"{target.title}\nМодель: {model}\nРазмер: {size}; изображений:1\n"
            f"Ожидаемый полный расход: {rub(quote.total)}\n"
            f"Референсов: {len(refs)} из {len(candidates)}. "
            "API может не вернуть фактическую сумму — тогда останется резерв.\n"
            + ("Цена Recraft выше вашего порога. Разрешить её разово?\n" if beyond else "")
            + "Отправить платный запрос?"
        )
        if (self.settings.confirm or beyond) and not self.ask("Подтверждение изображения", text):
            raise ValueError("Генерация отменена до отправки; списания нет.")
        references = []
        for asset in refs:
            raw = self.registry.asset_path(asset).read_bytes()
            references.append("data:image/png;base64," + base64.b64encode(raw).decode())
        if sum(map(len, references)) > 20 * 1024 * 1024:
            raise ValueError("Референсы превышают безопасный размер20МБ. Запрос не отправлен.")
        prompt = make_prompt(target, refs)
        body = payload(quote, prompt, references)
        registry = self.registry
        identity = registry.reserve(
            target.campaign, target.subject, model, quote.total, self.settings.monthly_micros
        )
        key = self._key

        def generate(transport):
            registry.mark_submitted(identity)
            try:
                png, actual, receipt = transport.generate(body, key)
                asset = registry.complete(
                    identity,
                    png,
                    type_id=target.type_id,
                    scope="type" if target.common else "instance",
                    prompt=prompt,
                    refs=[a["id"] for a in refs],
                    actual=actual,
                    receipt=receipt,
                )
                registry.bind(target.campaign, target.entity, target.subject)
                return asset
            except ImageError as error:
                registry.fail(identity, error.code)
                raise
            except Exception:
                registry.fail(identity, "storage_or_processing")
                raise

        self.stage = "generate"
        self.status(f"Генерация: {model}, резерв {rub(quote.total)}. Повтора не будет.")
        self.worker.start(generate)
        self.refresh_totals()

    def view(self, campaign, entity):
        asset = self.registry.latest_for(campaign, entity)
        if not asset:
            self.status("Для объекта ещё нет сохранённого изображения.")
            return
        versions = self.registry.versions(campaign, asset["subject"])
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Визуальная память · версии")
        dialog.resize(760, 820)
        layout = QVBoxLayout(dialog)
        choice = QComboBox()
        layout.addWidget(choice)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(label)
        layout.addWidget(scroll, 1)
        info = QLabel()
        info.setWordWrap(True)
        layout.addWidget(info)
        for row in versions:
            choice.addItem(f"Версия {row['version']} · {row['model']}")

        def show(index):
            row = versions[index]
            try:
                pixmap = QPixmap(str(self.registry.asset_path(row)))
                label.setPixmap(
                    pixmap.scaled(
                        680,
                        680,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                )
                info.setText(
                    f"{row['created']} · {row['model']}\n"
                    "Визуализация не изменяет канон и может отличаться от описания."
                )
            except (OSError, ValueError) as error:
                info.setText(str(error))

        choice.currentIndexChanged.connect(show)
        show(0)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def close(self):
        self.closed = True
        self.queue.clear()
        if not self.worker.busy:
            self.lock.unlock()


def install_visuals(window):
    window.visuals = VisualController(window)
    window.scene_image_button = QPushButton("Изобразить сцену")
    window.scene_image_button.clicked.connect(window.visuals.request_scene)
    window.tabs.widget(0).layout().addWidget(window.scene_image_button)
    panel = window.chronicles_panel
    row = QHBoxLayout()
    panel.visual_preview = QLabel("Образ пока не создан")
    panel.visual_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    panel.visual_preview.setMaximumHeight(105)
    panel.visual_preview.hide()
    panel.image_create = QPushButton("Создать изображение")
    panel.image_regenerate = QPushButton("Перегенерировать")
    panel.image_view = QPushButton("Посмотреть")
    panel.image_shared = QCheckBox("Общий образ типа")
    for b in (panel.image_create, panel.image_regenerate, panel.image_view, panel.image_shared):
        row.addWidget(b)
    panel.image_controls = QWidget()
    panel.image_controls.setLayout(row)
    panel.layout().addWidget(panel.image_controls)
    panel.image_menu_button = QPushButton("Изображение…")
    menu = QMenu(panel)
    panel.image_menu_button.setMenu(menu)
    panel.layout().itemAt(panel.layout().count() - 2).layout().addWidget(panel.image_menu_button)

    def selected():
        item = panel.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def request(regenerate=False):
        entry = selected()
        if entry:
            window.visuals.request_entry(
                entry, regenerate=regenerate, shared=panel.image_shared.isChecked()
            )

    menu.addAction("Создать изображение", lambda: request(False))
    menu.addAction("Перегенерировать", lambda: request(True))
    menu.addAction("Посмотреть версии", lambda: panel.image_view.click())
    shared_action = menu.addAction("Общий образ типа")
    shared_action.setCheckable(True)
    shared_action.toggled.connect(panel.image_shared.setChecked)
    panel.image_create.clicked.connect(lambda: request(False))
    panel.image_regenerate.clicked.connect(lambda: request(True))
    panel.image_view.clicked.connect(
        lambda: window.visuals.view(
            __import__(
                "rpg_vkr.storage.campaigns", fromlist=["CampaignRepository"]
            ).CampaignRepository.identity(window._session),
            selected().key,
        )
        if selected()
        else None
    )

    def refresh():
        from rpg_vkr.storage.campaigns import CampaignRepository

        entry = selected()
        asset = None
        for button in (panel.image_create, panel.image_view, panel.image_regenerate):
            button.setEnabled(bool(entry))
        if entry:
            asset = window.visuals.registry.latest_for(
                CampaignRepository.identity(window._session), entry.key
            )
            try:
                target = entity_target(window._session, entry)
                panel.image_shared.setEnabled(target.common)
                panel.image_shared.setChecked(target.common)
            except ValueError:
                panel.image_shared.setEnabled(False)
        shared_action.setChecked(panel.image_shared.isChecked())
        shared_action.setEnabled(panel.image_shared.isEnabled())
        panel.image_menu_button.setEnabled(bool(entry))
        if asset:
            try:
                pixmap = QPixmap(str(window.visuals.registry.asset_path(asset)))
                panel.visual_preview.setPixmap(
                    pixmap.scaled(
                        QSize(96, 96),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                )
                item = panel.list.currentItem()
                item.setIcon(QIcon(pixmap))
                from PySide6.QtCore import QUrl

                from rpg_vkr.ui.chronicles_panel import card_html

                url = QUrl.fromLocalFile(str(window.visuals.registry.asset_path(asset))).toString()
                panel.detail.setHtml(
                    card_html(entry) + f'<p><img src="{url}" width="96" height="96"></p>'
                )
            except (ValueError, OSError):
                panel.visual_preview.setText("Изображение повреждено")
        else:
            panel.visual_preview.setText("Образ пока не создан")
        panel.image_view.setEnabled(bool(asset))
        panel.image_regenerate.setEnabled(bool(asset))

    panel.list.currentItemChanged.connect(lambda *_: refresh())
    window.visuals.changed.connect(refresh)
    refresh()
    panel.image_controls.setVisible(panel.width() >= 850)
    panel.image_menu_button.setVisible(panel.width() < 850)
