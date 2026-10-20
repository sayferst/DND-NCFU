"""Independent bounded Images transport. One POST, no redirects, retries or chat API."""

import base64
import ipaddress
import json
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
from PySide6.QtGui import QImageReader

from rpg_vkr.narrative.cloud import validate_api_key
from rpg_vkr.narrative.routerai import parse_allowance

BASE = "https://routerai.ru/api/v1"
MAX_BYTES = 20 * 1024 * 1024


class ImageError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalized_png(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ImageError("image_size", "Некорректный размер файла изображения.")
    buffer = QBuffer()
    buffer.setData(QByteArray(raw))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if size.width() < 1 or size.height() < 1 or size.width() * size.height() > 16777216:
        raise ImageError("image_dimensions", "Файл не является допустимым изображением.")
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ImageError("image_decode", "Не удалось прочитать изображение.")
    result = QBuffer()
    result.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(result, "PNG"):
        raise ImageError("image_encode", "Не удалось сохранить изображение.")
    raw = bytes(result.data())
    if len(raw) > MAX_BYTES:
        raise ImageError("image_size", "Итоговый PNG превышает лимит20МБ.")
    return raw


class ImagesTransport:
    def __init__(self, *, test_base=None):
        if test_base:
            url = urllib.parse.urlsplit(test_base)
            if url.scheme != "http" or url.hostname != "127.0.0.1":
                raise ValueError("Test endpoint must be explicit loopback.")
        self.base = test_base or BASE
        self.test_base = test_base
        self.opener = urllib.request.build_opener(NoRedirect)

    def read(self, url, *, key="", payload=None, maximum=MAX_BYTES * 2, timeout=30):
        headers = {"Accept": "application/json"}
        if key:
            if not url.startswith(self.base + "/") or any(c.isspace() for c in key):
                raise ImageError("key", "Недопустимый адрес или формат ключа.")
            try:
                validate_api_key(key)
            except ValueError:
                raise ImageError("key", "Недопустимый формат ключа API.") from None
            headers["Authorization"] = "Bearer " + key
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers
        )
        try:
            with self.opener.open(request, timeout=timeout) as reply:
                raw = reply.read(maximum + 1)
                if len(raw) > maximum:
                    raise ImageError("response_size", "Ответ API слишком большой.")
                return raw
        except urllib.error.HTTPError as error:
            error.close()
            raise ImageError(
                "http_" + str(error.code), f"Images API: HTTP {error.code}; повтор не выполнен."
            ) from None
        except (OSError, urllib.error.URLError, TimeoutError):
            raise ImageError(
                "network", "Images API: ошибка сети или таймаут; повтор не выполнен."
            ) from None

    def metadata(self, key):
        try:
            data = json.loads(self.read(self.base + "/key", key=key, maximum=65536))
        except (ValueError, TypeError, RecursionError):
            raise ImageError(
                "metadata", "RouterAI вернул неверный JSON проверки ключа Художника."
            ) from None
        try:
            allowance = parse_allowance(data)
        except (ValueError, TypeError, RecursionError) as error:
            message = (
                str(error) if isinstance(error, ValueError) else "Неверный формат лимита ключа."
            )
            raise ImageError("allowance", message) from None
        return allowance, self.catalog()

    def catalog(self):
        try:
            return json.loads(self.read(self.base + "/models", maximum=16 * 1024 * 1024))
        except (ValueError, TypeError, RecursionError):
            raise ImageError("catalog", "Каталог изображений вернул неверный JSON.") from None

    def download(self, url):
        parsed = urllib.parse.urlsplit(url)
        if not (self.test_base and url.startswith(self.test_base + "/")):
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ImageError("image_url", "API вернул небезопасный адрес изображения.")
            try:
                addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
            except OSError:
                raise ImageError("image_url", "Не удалось проверить адрес изображения.") from None
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ImageError("image_url", "Внутренние адреса изображения запрещены.")
        # Never forward the RouterAI key to image/CDN URLs, even on the same host.
        return self.read(url, maximum=MAX_BYTES, timeout=60)

    def generate(self, payload, key):
        actual, receipt = None, ""
        try:
            data = json.loads(
                self.read(self.base + "/images", key=key, payload=payload, timeout=180)
            )
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            cost = data.get("cost_rub", usage.get("cost_rub"))
            currency = "RUB" if cost is not None else data.get("currency", usage.get("currency"))
            if cost is None:
                cost = data.get("cost", usage.get("cost"))
                # Images guide defines usage.cost in rubles. An explicit foreign
                # currency remains foreign, even on this endpoint.
                if currency is None and "cost" in usage and "cost" not in data:
                    currency = "RUB"
            billing = {}
            try:
                number = Decimal(str(cost))
                if number.is_finite() and 0 <= number <= Decimal("1000000000000"):
                    billing = {
                        "amount": str(number),
                        "currency": currency if currency in {"RUB", "USD", "EUR"} else "unknown",
                    }
                    if currency == "RUB":
                        actual = int((number * 1000000).to_integral_value(rounding="ROUND_CEILING"))
            except (ValueError, ArithmeticError):
                pass
            request_id = str(data.get("id", ""))
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id) or key in request_id:
                request_id = ""
            receipt = json.dumps({"id": request_id, "billing": billing}, ensure_ascii=False)
            rows = data["data"]
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError
            row = rows[0]
            if isinstance(row.get("b64_json"), str):
                if len(row["b64_json"]) > (MAX_BYTES * 4 // 3 + 8):
                    raise ValueError
                raw = base64.b64decode(row["b64_json"], validate=True)
            elif isinstance(row.get("url"), str):
                raw = self.download(row["url"])
            else:
                raise ValueError
            png = normalized_png(raw)
            return png, actual, receipt
        except ImageError as error:
            error.actual = actual
            error.receipt = receipt
            raise
        except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
            error = ImageError(
                "format", "Images API вернул неподдержанный формат; расход требует сверки."
            )
            error.actual, error.receipt = actual, receipt
            raise error from None


class ImagesWorker(QObject):
    finished = Signal(object)

    def __init__(self, parent=None, transport=None):
        super().__init__(parent)
        self.transport = transport or ImagesTransport()
        self.busy = False

    def start(self, work):
        if self.busy:
            raise ValueError("Уже выполняется запрос изображений.")
        self.busy = True

        def run():
            try:
                result = {"value": work(self.transport)}
            except ImageError as error:
                result = {"code": error.code, "error": str(error)}
            except Exception:
                result = {
                    "code": "internal",
                    "error": "Ошибка обработки изображения; подробности не содержат ключа.",
                }
            self.busy = False
            try:
                self.finished.emit(result)
            except RuntimeError:
                pass  # Window closed; work/ledger are already durable before this signal.

        threading.Thread(target=run, daemon=True).start()
