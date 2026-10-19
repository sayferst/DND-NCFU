"""Read-only RouterAI metadata: public prices and a restricted key's allowance.

No key creation, key editing, top-ups, model requests or master keys belong here.
The schema comes from the documentation excerpts supplied by the user.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

CATALOG_URL = "https://routerai.ru/api/v1/models"
KEY_URL = "https://routerai.ru/api/v1/key"
MAX_MONTHLY_RUB = Decimal("2000")
MODEL_ID = r"[A-Za-z0-9_.:/-]{1,128}"


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Нет корректной суммы в ответе RouterAI.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Неверная сумма в ответе RouterAI.") from error
    if not number.is_finite() or not 0 <= number <= Decimal("1000000000000"):
        raise ValueError("Неверная сумма в ответе RouterAI.")
    return number


@dataclass(frozen=True)
class ModelQuote:
    id: str
    prompt_rub: Decimal
    completion_rub: Decimal
    supported_parameters: tuple[str, ...]

    @property
    def label(self):
        return (
            f"{self.id} · вход {self.prompt_rub * 1_000_000:.2f} ₽/млн · "
            f"выход {self.completion_rub * 1_000_000:.2f} ₽/млн"
        )


def _data(value):
    # The supplied reference shows a one-element wrapper array as well as data.
    if (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and "data" in value[0]
    ):
        value = value[0]
    return value.get("data") if isinstance(value, dict) else value


def parse_models(data):
    rows = _data(data)
    if not isinstance(rows, list) or len(rows) > 10_000:
        raise ValueError("RouterAI не вернул каталог моделей.")
    quotes = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        if not re.fullmatch(MODEL_ID, row["id"]):
            continue
        prices, units = row.get("pricing"), row.get("pricing_units")
        if not isinstance(prices, dict) or not isinstance(units, dict):
            continue
        if units.get("prompt") != "token" or units.get("completion") != "token":
            continue  # A request/image/second must not be displayed as a token price.
        architecture = row.get("architecture") or {}
        if not isinstance(architecture, dict):
            continue
        outputs = architecture.get("output_modalities")
        if outputs is not None and (not isinstance(outputs, list) or "text" not in outputs):
            continue
        parameters = row.get("supported_parameters", [])
        if (
            not isinstance(parameters, list)
            or len(parameters) > 100
            or any(not isinstance(p, str) for p in parameters)
        ):
            continue
        try:
            quotes[row["id"]] = ModelQuote(
                row["id"],
                amount(prices.get("prompt")),
                amount(prices.get("completion")),
                tuple(parameters),
            )
        except ValueError:
            continue
    if not quotes:
        raise ValueError("В каталоге нет текстовых моделей с ценами в рублях за токен.")
    return tuple(quotes[key] for key in sorted(quotes))


@dataclass(frozen=True)
class KeyAllowance:
    limit: Decimal
    used_monthly: Decimal
    remaining: Decimal


def parse_allowance(data):
    row = _data(data)
    if isinstance(row, list) and len(row) == 1:
        row = row[0]
    if not isinstance(row, dict):
        raise ValueError("RouterAI не вернул данные текущего API-ключа.")
    if row.get("disabled") is not False:
        raise ValueError("Ключ RouterAI выключен или его статус не подтверждён.")
    if row.get("limit") is None:
        raise ValueError("У ключа RouterAI не подтверждён месячный лимит. Задайте его в кабинете.")
    limit = amount(row.get("limit"))
    if not 0 < limit <= MAX_MONTHLY_RUB:
        raise ValueError("Задайте у ключа RouterAI положительный месячный лимит не более 2000 ₽.")
    reset = row.get("limit_reset")
    if reset is not None and not isinstance(reset, str):
        raise ValueError("Не подтверждён период лимита ключа RouterAI.")
    if reset in {"daily", "weekly", "day", "week"}:
        raise ValueError("Нужен месячный лимит ключа RouterAI, не дневной или недельный.")
    used = amount(row.get("usage_monthly"))
    remaining = max(Decimal(0), limit - used)
    if row.get("limit_remaining") is not None:
        remaining = min(remaining, amount(row["limit_remaining"]))
    if remaining <= 0:
        raise ValueError("Месячный лимит RouterAI исчерпан. Генерация не началась.")
    return KeyAllowance(limit, used, remaining)


class RouterAIClient(QObject):
    catalog_ready = Signal(object)
    key_ready = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None, *, timeout_ms=12000):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.timeout_ms = timeout_ms
        self._reply = None
        self._buffer = bytearray()
        self._reason = ""
        self._kind = ""

    @property
    def busy(self):
        return self._reply is not None

    def cancel(self):
        reply, self._reply = self._reply, None
        self.timer.stop()
        if reply is not None:
            reply.abort()
            reply.deleteLater()
            self.busy_changed.emit(False)

    def list_models(self):
        self._get(CATALOG_URL, "catalog")

    def check_key(self, key):
        self._get(KEY_URL, "key", key)

    def _get(self, url, kind, key=""):
        self.cancel()
        self._kind, self._reason, self._buffer = kind, "", bytearray()
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        if key:
            request.setRawHeader(
                QByteArray(b"Authorization"), QByteArray(("Bearer " + key).encode())
            )
        self._reply = self.manager.get(request)
        reply = self._reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finished(reply))
        self.timer.start(self.timeout_ms)
        self.busy_changed.emit(True)

    def _timeout(self):
        if self._reply is not None:
            self._reason = "RouterAI не завершил проверку данных вовремя. Генерация не началась."
            self._reply.abort()

    def _read(self, reply):
        if reply is not self._reply:
            return
        maximum = 4 * 1024 * 1024 if self._kind == "catalog" else 65536
        self._buffer.extend(bytes(reply.read(maximum + 1 - len(self._buffer))))
        if len(self._buffer) > maximum:
            self._reason = "Ответ RouterAI о моделях/лимите слишком большой. Генерация не началась."
            reply.abort()

    def _finished(self, reply):
        if reply is not self._reply:
            return
        self._read(reply)
        self.timer.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        network_error = reply.error()
        self._reply = None
        reply.deleteLater()
        self.busy_changed.emit(False)
        if self._reason:
            self.failed.emit(self._reason)
            return
        if status != 200 or network_error != QNetworkReply.NetworkError.NoError:
            detail = {
                401: "проверьте обычный API-ключ",
                402: "недостаточно баланса",
                403: "доступ отклонён",
                429: "слишком много запросов",
            }.get(status, "проверьте соединение и доступ")
            self.failed.emit(f"RouterAI: {detail} (HTTP {status}). Генерация не началась.")
            return
        try:
            data = json.loads(bytes(self._buffer))
        except (ValueError, TypeError, RecursionError):
            self.failed.emit("RouterAI вернул неверный JSON метаданных. Генерация не началась.")
            return
        try:
            if self._kind == "catalog":
                self.catalog_ready.emit(parse_models(data))
            else:
                self.key_ready.emit(parse_allowance(data))
        except ValueError as error:
            self.failed.emit(str(error))  # Our own bounded parser messages contain no account data.
        except (TypeError, KeyError, RecursionError):
            # Never echo raw key/account/error responses into logs or the journal.
            self.failed.emit(
                "Не удалось проверить каталог или месячный лимит RouterAI. Генерация не началась."
            )
