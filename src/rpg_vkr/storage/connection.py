"""Nonsecret UI preferences and opt-in Windows user-scoped DPAPI credentials."""

import ctypes
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from rpg_vkr.ui.workspace_tools import atomic_text

FLASH_MODEL = "~deepseek/deepseek-v4-flash-latest"


@dataclass(frozen=True)
class ConnectionPreferences:
    provider: str = "local"
    model: str = ""
    enabled: bool = False
    consent: bool = False

    def __post_init__(self):
        if self.provider not in {"local", "routerai", "openrouter", "openai"}:
            raise ValueError("Unknown provider preference")
        if (
            not isinstance(self.model, str)
            or self.model
            and not re.fullmatch(r"~?[A-Za-z0-9_.:/-]{1,128}", self.model)
        ):
            raise ValueError("Invalid model preference")
        if type(self.enabled) is not bool or type(self.consent) is not bool:
            raise ValueError("Invalid connection preference")

    def save(self, path):
        atomic_text(Path(path), json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls, path):
        try:
            path = Path(path)
            if path.stat().st_size > 4096:
                return cls()
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return cls()


def windows_credentials_available():
    return os.name == "nt"


def _dpapi(value, *, decrypt=False):
    if not windows_credentials_available():
        raise OSError("Защищённое сохранение ключа доступно на Windows.")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    source = ctypes.create_string_buffer(value)
    incoming = Blob(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError("Windows не удалось открыть или защитить ключ текущего пользователя.")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


def save_secret(path, key):
    if not isinstance(key, str) or not 1 <= len(key) <= 4096 or any(c.isspace() for c in key):
        raise ValueError("Нужен обычный API-ключ без пробелов.")
    encrypted = b"DND-DPAPI-1\0" + _dpapi(key.encode("utf-8"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def load_secret(path):
    try:
        with Path(path).open("rb") as stream:
            value = stream.read(16385)
        prefix = b"DND-DPAPI-1\0"
        if len(value) > 16384 or not value.startswith(prefix):
            return ""
        key = _dpapi(value[len(prefix) :], decrypt=True).decode("utf-8")
        return key if key and len(key) <= 4096 and not any(c.isspace() for c in key) else ""
    except (OSError, ValueError, UnicodeError):
        return ""
