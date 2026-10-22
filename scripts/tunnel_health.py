"""Public gateway health and bounded Cloudflare error classification, without credentials."""

import http.client
import json
import re
import socket
import ssl
import urllib.error
import urllib.request

from rpg_vkr.discovery import NoRedirect, public_endpoint
from rpg_vkr.gateway_http import gateway_headers

EXPECTED = {"service": "dnd-gateway", "protocol": 1, "async_jobs": True}
CF_ERRORS = {
    "1033": "Cloudflare не видит подключённый коннектор туннеля",
    "1016": "Cloudflare не разрешает адрес назначения туннеля",
    "1000": "Cloudflare отклонил DNS-адрес назначения",
}


def classify_cloudflare(raw, headers):
    # Never return a body, hostname, ray identifier or arbitrary header value.
    text = re.sub(r"<[^>]{0,512}>", " ", raw[:16384].decode("utf-8", errors="replace"))
    match = re.search(r"\berror(?:\s+code)?\s*[:#]?\s*(10\d{2})\b", text, re.I)
    code = match[1] if match and match[1] in CF_ERRORS else ""
    return {
        "cloudflare_code": code,
        "cloudflare_header": bool(headers and headers.get("cf-ray")),
    }


def probe(endpoint, *, direct=False):
    request = urllib.request.Request(
        public_endpoint(endpoint) + "/health",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            **gateway_headers(endpoint),
        },
    )
    handlers = [NoRedirect()]
    if direct:
        handlers.append(urllib.request.ProxyHandler({}))
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=10) as response:
            value = json.loads(response.read(2049))
            if response.status != 200 or value != EXPECTED:
                raise ValueError("Шлюз не прошёл проверку доступности.")
            return {"ok": True, "http_status": 200}
    except urllib.error.HTTPError as error:
        try:
            error.gateway_details = classify_cloudflare(error.read(16384), error.headers)
        except (ValueError, OSError, http.client.HTTPException):
            error.gateway_details = {"cloudflare_code": "", "cloudflare_header": False}
        finally:
            error.close()
        raise
    except http.client.HTTPException:
        raise urllib.error.URLError("gateway transport incomplete") from None


def result(endpoint, *, direct=False):
    try:
        return probe(endpoint, direct=direct)
    except urllib.error.HTTPError as error:
        return {"ok": False, "http_status": error.code, **getattr(error, "gateway_details", {})}
    except (OSError, ValueError) as error:
        cause = error.reason if isinstance(error, urllib.error.URLError) else error
        kind = (
            "dns"
            if isinstance(cause, socket.gaierror)
            else "tls"
            if isinstance(cause, ssl.SSLError)
            else "timeout"
            if isinstance(cause, TimeoutError)
            else "network"
            if isinstance(cause, OSError)
            else "invalid_health"
        )
        return {"ok": False, "error": kind}
