"""Background discovery/one-install activation; never blocks the Qt event loop."""

import json
import secrets
import threading
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal

from rpg_vkr.discovery import NoRedirect, fetch
from rpg_vkr.gateway_http import gateway_headers
from rpg_vkr.resources import resource_path
from rpg_vkr.storage.connection import load_secret, save_secret
from rpg_vkr.ui.workspace_tools import atomic_text


class ConnectionWorker(QObject):
    finished = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.timer = QTimer(self)
        self.timer.setInterval(60000)
        self.timer.timeout.connect(self.start)
        self.finished.connect(self.apply)
        self.timer.start()
        QTimer.singleShot(0, self.start)

    def start(self):
        if self.busy or self.window.release_profile.mode != "tester":
            return
        self.busy = True
        window = self.window
        profile = window.release_profile
        root = window._saves.directory.parent
        token = window._tester_token

        def run():
            try:
                previous = 0
                state = root / "tester-discovery.json"
                if state.exists():
                    saved = json.loads(state.read_text(encoding="utf-8"))
                    if saved.get("key") == profile.verification_key:
                        previous = int(saved["sequence"])
                value = fetch(profile.discovery, profile.verification_key, previous=previous)
                atomic_text(
                    state,
                    json.dumps({"key": profile.verification_key, "sequence": value["sequence"]}),
                )
                access = token
                if not access:
                    path = resource_path("tester-bootstrap.json")
                    if not path.is_file() or path.stat().st_size > 512:
                        raise ValueError(
                            "В сборке нет персональной активации. Обратитесь к владельцу."
                        )
                    code = json.loads(path.read_text(encoding="utf-8"))["code"]
                    # Persist the installation secret BEFORE contacting the server. A lost reply
                    # is recoverable with the same secret; another installation cannot claim it.
                    secret_path = root / "tester-installation.bin"
                    installation = load_secret(secret_path)
                    if not installation:
                        installation = secrets.token_urlsafe(32)
                        save_secret(secret_path, installation)
                    body = json.dumps({"code": code, "installation": installation}).encode()
                    request = urllib.request.Request(
                        value["endpoint"] + "/activate",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            **gateway_headers(value["endpoint"]),
                        },
                    )
                    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as reply:
                        access = json.loads(reply.read(2048))["token"]
                    import re

                    if not isinstance(access, str) or not re.fullmatch(r"[a-f0-9]{64}", access):
                        raise ValueError("Неверный ответ активации.")
                    save_secret(root / "tester-access.bin", access)
                result = {"endpoint": value["endpoint"], "token": access}
            except Exception:
                # Never echo provider replies, bearer codes, URLs with credentials or tracebacks.
                result = {
                    "error": "Тестовая игра пока недоступна. Проверка повторится автоматически. "
                    "Если ошибка сохраняется, обратитесь к владельцу."
                }
            try:
                self.finished.emit(result)
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def apply(self, result):
        self.busy = False
        if self.window.release_profile.mode != "tester":
            return
        if "error" in result:
            # An expired/unverifiable manifest cannot keep authorizing future requests.
            self.window._tester_endpoint = ""
            self.window.statusBar().showMessage(result["error"])
            return
        self.window._tester_endpoint = result["endpoint"]
        self.window._tester_token = result["token"]
        from rpg_vkr.ui.tester_connection import configure

        # Existing operations keep their original endpoint/key until completed.
        if not self.window.ollama.busy and not self.window.visuals.worker.busy:
            configure(self.window)
        self.window.statusBar().showMessage(
            "Тестовая игра подключена. Можно создавать новую легенду.", 15000
        )
