"""Public release profile. A tester installation never falls back to owner credentials."""

import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from rpg_vkr.resources import resource_path


def gateway_url(value):
    parsed = urlsplit(value)
    loopback = parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
    if (
        (parsed.scheme != "https" and not loopback)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Нужен HTTPS-адрес игрового сервиса.")
    if parsed.path.rstrip("/") not in ("", "/api/v1"):
        raise ValueError("Недопустимый путь игрового сервиса.")
    return value.rstrip("/").removesuffix("/api/v1") + "/api/v1"


@dataclass(frozen=True)
class ReleaseProfile:
    mode: str = "developer"
    gateway: str = ""
    text_model: str = "deepseek/deepseek-v4-flash-latest"
    commit: str = "source"

    def __post_init__(self):
        if self.mode not in {"developer", "tester"}:
            raise ValueError("Неизвестный профиль сборки.")
        if self.gateway:
            object.__setattr__(self, "gateway", gateway_url(self.gateway))
        if not re.fullmatch(r"deepseek/[A-Za-z0-9_.-]*flash[A-Za-z0-9_.-]*", self.text_model):
            raise ValueError("Неизвестная модель тестовой сборки.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", self.commit):
            raise ValueError("Неизвестная версия сборки.")


def load_release_profile():
    path = resource_path("release-profile.json")
    if not path.exists():
        return ReleaseProfile()
    if path.stat().st_size > 4096:
        raise ValueError("Повреждён профиль сборки.")
    value = json.loads(path.read_text(encoding="utf-8"))
    # Build configuration must never contain a RouterAI key or a tester token.
    if not isinstance(value, dict) or set(value) - {"mode", "gateway", "text_model", "commit"}:
        raise ValueError("Повреждён профиль сборки.")
    return ReleaseProfile(**value)


def tester_token(window):
    return getattr(window, "_tester_token", "") or os.environ.get("DND_TESTER_TOKEN", "")
