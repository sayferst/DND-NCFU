"""One authenticated console reusing the original Master and Artist widgets."""

import json
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.build_info import VERSION
from rpg_vkr.ui.developer_access import DeveloperAccess

TECHNICAL = {"Мастер", "Рассказчик", "Художник", "Разработчик"}


def plain(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class DeveloperConsole(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.access = DeveloperAccess(window._saves.directory.parent / "developer-access.json")
        self.pages = QTabWidget()
        self.pages.setUsesScrollButtons(True)
        self.originals = {}
        layout = QVBoxLayout(self)
        layout.addWidget(plain("КОНСОЛЬ РАЗРАБОТЧИКА · локальный доступ к настройкам"))
        layout.addWidget(self.pages, 1)
        # Reparent, do not duplicate controllers or forms.
        for name in ("Мастер", "Художник"):
            for index in range(window.tabs.count()):
                if window.tabs.tabText(index) == name:
                    page = window.tabs.widget(index)
                    window.tabs.removeTab(index)
                    self.originals[name] = page
                    self.pages.addTab(page, "ИИ-" + name.lower())
                    break
        self.connection = QWidget()
        form = QFormLayout(self.connection)
        self.connection_info = plain(
            "Подключение владельца: настройки в «ИИ-мастер» и «ИИ-художник»."
        )
        form.addRow(self.connection_info)
        # Remove technical shortcuts from player settings too.
        for button in (window.flash_configure,):
            window.settings_form.removeWidget(button)
            form.addRow(button)
        for button in window.findChildren(QPushButton):
            if button.text().startswith("Открыть Художника:"):
                window.settings_form.removeWidget(button)
                form.addRow(button)
        self.pages.addTab(self.connection, "Подключения")
        self.budget = QWidget()
        budget_layout = QVBoxLayout(self.budget)
        self.budget_info = plain("")
        budget_layout.addWidget(self.budget_info)
        self.open_budget = QPushButton("Бюджет и история изображений")
        self.open_budget.clicked.connect(lambda: window.artist_panel.show_budget())
        budget_layout.addWidget(self.open_budget)
        budget_layout.addStretch()
        self.pages.addTab(self.budget, "Бюджет и ограничения")
        diagnostics = QWidget()
        diag = QVBoxLayout(diagnostics)
        self.report = QTextBrowser()
        diag.addWidget(self.report)
        check = QPushButton("Self-check ресурсов · без сети")
        check.clicked.connect(self.self_check)
        diag.addWidget(check)
        export = QPushButton("Экспорт безопасного отчёта…")
        export.clicked.connect(self.export)
        diag.addWidget(export)
        self.pages.addTab(diagnostics, "Диагностика")
        testing = QWidget()
        testing_layout = QVBoxLayout(testing)
        testing_layout.addWidget(
            plain(
                "Закрытое тестирование: персональный отзывный допуск выдаётся серверной CLI. "
                "Локальный пароль не управляет сервером или общим бюджетом. "
                "Инструкция: docs/TESTER_GATEWAY.md."
            )
        )
        self.testing_info = plain("Профиль владельца. Сервер не проверялся.")
        testing_layout.addWidget(self.testing_info)
        testing_layout.addStretch()
        self.pages.addTab(testing, "Управление тестированием")
        change = QPushButton("Сменить локальный пароль…")
        change.clicked.connect(self.change_password)
        layout.addWidget(change)
        logout = QPushButton("Выйти из режима разработчика")
        logout.clicked.connect(self.logout)
        layout.addWidget(logout)
        self.pages.currentChanged.connect(lambda _: self.refresh())
        self._safe_report = {}

    def enter(self, name="Разработчик"):
        if not self.access.authorized:
            dialog = QDialog(self.window)
            dialog.setWindowTitle("Доступ разработчика")
            layout = QVBoxLayout(dialog)
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setAccessibleName("Пароль разработчика")
            layout.addWidget(field)
            status = plain("")
            layout.addWidget(status)
            buttons = QDialogButtonBox()
            login = buttons.addButton("Войти", QDialogButtonBox.ButtonRole.AcceptRole)
            cancel = buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
            cancel.clicked.connect(dialog.reject)
            layout.addWidget(buttons)

            def verify():
                if self.access.login(field.text()):
                    field.clear()
                    dialog.accept()
                else:
                    field.clear()
                    status.setText(
                        "Подождите 30 секунд."
                        if self.access.clock() < self.access.blocked_until
                        else "Неверный пароль"
                    )

            login.clicked.connect(verify)
            field.returnPressed.connect(verify)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
        if name in self.originals:
            self.pages.setCurrentWidget(self.originals[name])
        self.window.tabs.setTabVisible(self.window.tabs.indexOf(self), True)
        self.window.tabs.setCurrentWidget(self)
        self.refresh()
        return True

    def logout(self):
        self.access.logout()
        self.window.open_section("Главное меню")
        self.window.tabs.setTabVisible(self.window.tabs.indexOf(self), False)

    def refresh(self):
        if not self.access.authorized:
            return
        visual = getattr(self.window, "visuals", None)
        totals = visual.registry.totals() if visual else {}
        self._safe_report = {
            "version": VERSION,
            "sqlite": sqlite3.sqlite_version,
            "campaign_loaded": bool(self.window._session.generated_world),
            "saved_slots": [self.window._saves.path(i).exists() for i in (1, 2, 3)]
            if hasattr(self.window._saves, "path")
            else "см. Сохранения",
            "visual_totals": totals,
            "text_metrics": self.window.narrator_metrics.text(),
        }
        self.budget_info.setText(
            "Текст: "
            + self.window.narrator_metrics.text()
            + "\nИзображения: "
            + json.dumps(totals, ensure_ascii=False)
            + "\nЛокальные лимиты не заменяют серверные квоты тестировщиков."
        )
        self.report.setPlainText(json.dumps(self._safe_report, ensure_ascii=False, indent=2))

    def self_check(self):
        if not self.access.authorized:
            return
        from rpg_vkr.self_check import check_resources

        try:
            result = check_resources()
            # Do not export machine paths or environment details.
            self._safe_report["self_check"] = {k: result[k] for k in ("ok", "resources", "qt_tls")}
        except Exception:
            self._safe_report["self_check"] = {"ok": False}
        self.report.setPlainText(json.dumps(self._safe_report, ensure_ascii=False, indent=2))

    def export(self):
        if not self.access.authorized:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Безопасная диагностика", "diagnostics.json")
        if path:
            try:
                with open(path, "x", encoding="utf-8") as stream:
                    json.dump(self._safe_report, stream, ensure_ascii=False, indent=2)
            except OSError:
                self.report.setPlainText("Не удалось записать отчёт. Выберите новый файл.")

    def change_password(self):
        if not self.access.authorized:
            return
        current, ok = QInputDialog.getText(
            self, "Смена пароля", "Текущий пароль", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        replacement, ok = QInputDialog.getText(
            self, "Смена пароля", "Новый пароль · 8–128 символов", QLineEdit.EchoMode.Password
        )
        if ok:
            try:
                self.access.change_password(current, replacement)
                self.report.setPlainText(
                    "Пароль изменён. Вход после перезапуска потребует новый пароль."
                )
            except (ValueError, OSError) as error:
                self.report.setPlainText(str(error))


def install_developer(window):
    window.developer_console = DeveloperConsole(window)
    window.tabs.addTab(window.developer_console, "Разработчик")
    window.tabs.setTabVisible(window.tabs.indexOf(window.developer_console), False)
    # Rebuild hidden compatibility picker after original pages have been moved.
    window.navigation.blockSignals(True)
    window.navigation.clear()
    for i in range(window.tabs.count()):
        if window.tabs.tabText(i) != "Разработчик":
            window.navigation.addItem(window.tabs.tabText(i), i)
    window.navigation.blockSignals(False)
