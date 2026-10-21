"""Local UI lock only. This deliberately confers no server authority."""

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from rpg_vkr.ui.workspace_tools import atomic_text

ITERATIONS = 240000
DEFAULT_SALT = b"DND-NCFU-local-access-v1"
DEFAULT_VERIFIER = "85d7bdd426c5b24f69e8be55d88910c7dfc945ea1fb8ad1484a64cb41dd65e0d"


class DeveloperAccess:
    def __init__(self, path, clock=time.monotonic):
        self.path = Path(path)
        self.clock = clock
        self.authorized = False
        self.failures = 0
        self.blocked_until = 0
        self.salt, self.verifier = DEFAULT_SALT, DEFAULT_VERIFIER
        if self.path.exists():
            # Fail closed if a saved owner password is corrupt, never restore the default.
            try:
                if self.path.stat().st_size > 2048:
                    raise ValueError
                value = json.loads(self.path.read_text(encoding="utf-8"))
                salt = bytes.fromhex(value["salt"])
                verifier = value["verifier"]
                if len(salt) != 24 or len(bytes.fromhex(verifier)) != 32:
                    raise ValueError
                self.salt, self.verifier = salt, verifier
            except (ValueError, KeyError, OSError, TypeError):
                self.verifier = ""

    def login(self, password):
        if self.clock() < self.blocked_until or not isinstance(password, str):
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), self.salt, ITERATIONS).hex()
        if self.verifier and hmac.compare_digest(candidate, self.verifier):
            self.authorized, self.failures = True, 0
            return True
        self.failures += 1
        if self.failures >= 5:
            self.blocked_until = self.clock() + 30
            self.failures = 0
        return False

    def logout(self):
        self.authorized = False

    def change_password(self, current, replacement):
        if not self.authorized or not self.login(current):
            raise ValueError("Текущий пароль не подтверждён.")
        if not isinstance(replacement, str) or not 8 <= len(replacement) <= 128:
            raise ValueError("Новый пароль должен содержать от 8 до 128 символов.")
        salt = secrets.token_bytes(24)
        verifier = hashlib.pbkdf2_hmac("sha256", replacement.encode(), salt, ITERATIONS).hex()
        atomic_text(self.path, json.dumps({"salt": salt.hex(), "verifier": verifier}))
        self.salt, self.verifier = salt, verifier
