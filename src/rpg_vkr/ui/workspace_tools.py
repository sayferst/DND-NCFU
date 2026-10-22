"""Local reading preferences and plain-text exports, independent of game saves."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit


@dataclass(frozen=True)
class ReadingPreferences:
    font_size: int = 13
    theme: str = "Системная"
    bold_text: bool = True
    animations: int = 0

    def __post_init__(self) -> None:
        if type(self.animations) is not int or self.animations not in (0, 1, 2):
            raise ValueError("Неизвестный режим анимаций.")
        if type(self.font_size) is not int or not 9 <= self.font_size <= 20:
            raise ValueError("Размер шрифта должен быть от 9 до 20.")
        if type(self.bold_text) is not bool:
            raise ValueError("Жирность текста должна быть булевым значением.")
        if self.theme not in ("Системная", "Светлая", "Тёмная"):
            raise ValueError("Неизвестная тема.")


def atomic_text(path: Path, text: str) -> None:
    """Replace only after successful write; keep an existing destination on failure."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Cleanup must not hide the original write failure.


def load_preferences(path: Path) -> tuple[ReadingPreferences, str]:
    try:
        if path.stat().st_size > 4096:
            raise ValueError("Файл настроек слишком большой.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) not in (
            {"font_size", "theme"},
            {"font_size", "theme", "bold_text"},
            {"font_size", "theme", "bold_text", "animations"},
        ):
            raise ValueError("Неверный формат настроек.")
        preferences = ReadingPreferences(**data)
        if "bold_text" not in data:
            preferences = ReadingPreferences(
                min(20, preferences.font_size + 2), preferences.theme, True
            )
        return preferences, ""
    except FileNotFoundError:
        return ReadingPreferences(), ""
    except (OSError, ValueError, TypeError):
        return ReadingPreferences(), "Настройки чтения недоступны: применены стандартные."


def save_preferences(path: Path, preferences: ReadingPreferences) -> None:
    atomic_text(path, json.dumps(asdict(preferences), ensure_ascii=False, indent=2) + "\n")


class HistoryLineEdit(QLineEdit):
    """Up/Down browse at most 100 submitted actions and restore the current draft."""

    def __init__(self) -> None:
        super().__init__()
        self.set_history([])

    def set_history(self, actions: list[str]) -> None:
        self._history = actions[-100:]
        self._position = len(self._history)
        self._draft = ""

    def remember(self, action: str) -> None:
        self.set_history([*self._history, action])

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not event.modifiers():
            if self._position == len(self._history):
                self._draft = self.text()
            direction = -1 if event.key() == Qt.Key.Key_Up else 1
            self._position = max(0, min(len(self._history), self._position + direction))
            self.setText(
                self._draft
                if self._position == len(self._history)
                else self._history[self._position]
            )
            return
        super().keyPressEvent(event)
