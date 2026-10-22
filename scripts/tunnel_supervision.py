"""Availability state and bounded connector recovery, independent of API grants."""

import json
import tempfile
from pathlib import Path


class RestartTunnel(ValueError):
    pass


def write_ready(root, ready):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(ready, stream)
        temporary.replace(root / "host-ready.json")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class PublicMonitor:
    def __init__(self, root, ready):
        self.root = root
        self.ready = ready
        self.failures = 0
        self.successes = 3  # Initial signed/public stability gate has already passed.

    def check(self, probe, reason):
        try:
            probe()
        except (ValueError, OSError) as error:
            self.failures += 1
            self.successes = 0
            (self.root / "host-ready.json").unlink(missing_ok=True)
            message = reason(error)
            if self.failures >= 3:
                raise RestartTunnel("Публичное соединение потеряно: " + message) from None
            return message
        self.failures = 0
        self.successes = min(3, self.successes + 1)
        if self.successes == 3:
            write_ready(self.root, self.ready)
            return ""
        return "проверяю устойчивость восстановленного соединения"


class RestartBudget:
    def __init__(self):
        self.restarts = []

    def delay(self, now):
        self.restarts = [stamp for stamp in self.restarts if now - stamp < 3600]
        if len(self.restarts) >= 3:
            raise ValueError(
                "Туннель не удерживает соединение: три восстановления за час не помогли. "
                "Автопопытки остановлены. Нужна проверка сети/VPN на Windows. "
                "Допуски и расходы сохранены."
            )
        self.restarts.append(now)
        return (5, 15, 30)[len(self.restarts) - 1]
