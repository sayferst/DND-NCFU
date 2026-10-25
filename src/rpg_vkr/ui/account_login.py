"""Account login over verified discovery; passwords are never saved on the client."""

import json
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit, QPushButton

from rpg_vkr.discovery import NoRedirect, fetch
from rpg_vkr.gateway_http import gateway_headers


class LoginDialog(QDialog):
    finished_login = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("DND-NCFU · Вход в тестовую игру")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)
        self.username = QLineEdit()
        self.username.setPlaceholderText("admin или tester")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.status = QLabel("Войдите в учётную запись. Требуются интернет и работающий хост.")
        self.status.setWordWrap(True)
        self.submit = QPushButton("Войти")
        layout.addRow("Логин", self.username)
        layout.addRow("Пароль", self.password)
        layout.addRow(self.status)
        layout.addRow(self.submit)
        self.submit.clicked.connect(self.login)
        self.password.returnPressed.connect(self.login)
        self.finished_login.connect(self.apply)

    def login(self):
        if not self.submit.isEnabled():
            return
        name, password = self.username.text().strip(), self.password.text()
        self.password.clear()
        if name not in {"admin", "tester"} or not password:
            self.status.setText("Укажите логин admin или tester и пароль.")
            return
        self.submit.setEnabled(False)
        self.status.setText("Проверяется адрес хоста и учётная запись…")
        profile = self.window.release_profile

        def run():
            try:
                endpoint = profile.gateway
                if profile.discovery:
                    endpoint = fetch(profile.discovery, profile.verification_key)["endpoint"]
                request = urllib.request.Request(
                    endpoint + "/login",
                    data=json.dumps({"login": name, "password": password}).encode(),
                    headers={"Content-Type": "application/json", **gateway_headers(endpoint)},
                )
                with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
                    value = json.loads(response.read(4097))
                import re

                if (
                    not isinstance(value, dict)
                    or value.get("account") != name
                    or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", value.get("token", ""))
                ):
                    raise ValueError
                value["endpoint"] = endpoint
            except Exception:
                value = {"error": True}
            try:
                self.finished_login.emit(value)
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def apply(self, result):
        self.submit.setEnabled(True)
        if not self.isVisible() or self.window.release_profile.mode != "tester":
            return
        if "error" in result:
            self.status.setText(
                "Вход не выполнен: проверьте пароль и доступность хоста. "
                "После пяти неверных попыток подождите минуту."
            )
            return
        from rpg_vkr.ui.flash_settings import disconnect
        from rpg_vkr.ui.tester_connection import configure

        disconnect(self.window)
        self.window.visuals.cancel()
        self.window._tester_token = result["token"]
        self.window._account_name = result["account"]
        self.window.developer_console.access.authorized = result["account"] == "admin"
        if result["account"] != "admin":
            self.window.developer_console.logout()
        self.window._tester_endpoint = result["endpoint"]
        configure(self.window)
        self.window.statusBar().showMessage(
            f"Вход: {result['account']} · бюджет {result['budget_rub']} ₽."
        )
        self.accept()


def show_login(window):
    dialog = LoginDialog(window)
    dialog.exec()
    if not getattr(window, "_tester_token", ""):
        window.close()


class ConnectionCheck(QObject):
    completed = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.busy = False
        self.window = window
        self.completed.connect(self.apply)

    def start(self):
        if self.busy:
            return
        self.busy = True
        self.window.statusBar().showMessage("Проверяется сопряжение с хостом…")
        profile = self.window.release_profile

        def run():
            try:
                endpoint = profile.gateway
                if profile.discovery:
                    endpoint = fetch(profile.discovery, profile.verification_key)["endpoint"]
                request = urllib.request.Request(
                    endpoint + "/health", headers=gateway_headers(endpoint)
                )
                with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as reply:
                    value = json.loads(reply.read(2049))
                if value != {"service": "dnd-gateway", "protocol": 1, "async_jobs": True}:
                    raise ValueError
                message = "Сопряжение установлено: хост доступен. Генерация не запускалась."
            except Exception:
                message = "Хост недоступен. Проверьте интернет и запуск START_HOST.bat у владельца."
            try:
                self.completed.emit(message)
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def apply(self, message):
        self.busy = False
        self.window.statusBar().showMessage(message)


def check_connection(window):
    if not hasattr(window, "account_connection_check"):
        window.account_connection_check = ConnectionCheck(window)
    window.account_connection_check.start()
