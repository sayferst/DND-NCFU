"""Minimal crash reports: no exception messages, locals, prompts, headers or campaign text."""

import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from rpg_vkr.build_info import VERSION
from rpg_vkr.resources import data_directory


def record_error(error, tb=None):
    # Messages/locals can contain a full API response or secret key; omit them entirely.
    value = {
        "version": VERSION,
        "time_utc": datetime.now(UTC).isoformat(),
        "error_type": type(error).__name__,
        "frames": [
            {"module": Path(f.filename).name, "line": f.lineno, "function": f.name}
            for f in traceback.extract_tb(tb or error.__traceback__)[-30:]
        ],
    }
    try:
        folder = data_directory() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("error-" + uuid4().hex + ".json")
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        return path
    except (OSError, ValueError):
        return None


def show_error(error, tb=None):
    path = record_error(error, tb)
    message = "Не удалось выполнить операцию приложения. "
    message += f"Тип: {type(error).__name__}. "
    message += (
        f"Диагностика: {path}"
        if path
        else "Не удалось записать диагностику; проверьте папку данных."
    )
    if sys.stderr:
        sys.stderr.write(message + "\n")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "DND-NCFU — ошибка", message)
        return app
    except Exception:
        return None
