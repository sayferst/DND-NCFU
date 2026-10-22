"""Signed public endpoint discovery. No credentials are sent to the discovery host."""

import base64
import ipaddress
import json
import re
import time
import urllib.request
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from rpg_vkr.deployment import gateway_url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def discovery_url(value):
    # One public file in the existing owner's repository. No arbitrary discovery hosts.
    if not re.fullmatch(
        r"https://raw\.githubusercontent\.com/sayferst/DND-NCFU/[A-Za-z0-9_.-]+/endpoint\.json",
        value,
    ):
        raise ValueError("Неверная ссылка обновления игрового сервиса.")
    return value


def public_endpoint(value):
    value = gateway_url(value)
    url = urlsplit(value)
    if url.scheme != "https" or url.port not in (None, 443):
        raise ValueError("Игровой сервис должен использовать публичный HTTPS.")
    host = url.hostname
    if host == "localhost" or "." not in host or host.endswith((".local", ".localhost")):
        raise ValueError("Локальный адрес игрового сервиса запрещён.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Частный адрес игрового сервиса запрещён.")
    return value


def verify(raw, public_key, *, previous=0, now=None):
    if len(raw) > 8192:
        raise ValueError("Слишком большой документ адреса.")
    try:
        value = json.loads(raw)
        if set(value) != {"version", "sequence", "issued", "expires", "endpoint", "signature"}:
            raise ValueError
        signature = base64.b64decode(value.pop("signature"), validate=True)
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(signature, canonical(value))
        clock = time.time() if now is None else now
        if (
            value["version"] != 1
            or type(value["sequence"]) is not int
            or value["sequence"] < previous
            or value["sequence"] < 1
            or type(value["issued"]) is not int
            or type(value["expires"]) is not int
            or value["issued"] > clock + 300
            or value["expires"] <= clock
            or not 0 < value["expires"] - value["issued"] <= 35 * 86400
        ):
            raise ValueError
        value["endpoint"] = public_endpoint(value["endpoint"])
        return value
    except (InvalidSignature, ValueError, TypeError, KeyError, RecursionError):
        raise ValueError(
            "Подпись, срок или версия адреса игрового сервиса не прошли проверку."
        ) from None


def fetch(url, public_key, *, previous=0):
    request = urllib.request.Request(
        discovery_url(url) + "?t=" + str(int(time.time())),
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as reply:
        if reply.status != 200:
            raise ValueError("Документ адреса недоступен.")
        return verify(reply.read(8193), public_key, previous=previous)
