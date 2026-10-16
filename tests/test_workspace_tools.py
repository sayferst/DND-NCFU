"""Reading state and export failures must not affect the player's slots."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from rpg_vkr.ui.workspace_tools import (
    HistoryLineEdit,
    ReadingPreferences,
    atomic_text,
    load_preferences,
    save_preferences,
)


def test_preferences_round_trip_and_missing_file_does_not_create_directory(tmp_path):
    path = tmp_path / "data" / "reading.json"
    assert load_preferences(path) == (ReadingPreferences(), "")
    assert not path.parent.exists()
    save_preferences(path, ReadingPreferences(18, "Тёмная"))
    assert load_preferences(path) == (ReadingPreferences(18, "Тёмная"), "")


@pytest.mark.parametrize(
    "content",
    [
        "{broken",
        "[]",
        '{"font_size": true, "theme": "Системная"}',
        '{"font_size": 21, "theme": "Системная"}',
        '{"font_size": 11, "theme": "unknown"}',
        '{"font_size": 11, "theme": []}',
        '{"font_size": 11, "theme": "Системная", "extra": 1}',
        '{"font_size": 13, "theme": "Системная", "bold_text": 1}',
        '{"font_size": 13, "theme": "Системная", "bold_text": "true"}',
        " " * 4097,
    ],
)
def test_invalid_reading_file_falls_back_without_overwriting(tmp_path, content):
    path = tmp_path / "reading.json"
    path.write_text(content, encoding="utf-8")
    preferences, warning = load_preferences(path)
    assert preferences == ReadingPreferences()
    assert warning
    assert path.read_text(encoding="utf-8") == content


def test_export_atomic_failure_keeps_previous_bytes_and_cleans_temporary(tmp_path, monkeypatch):
    path = tmp_path / "journal.txt"
    path.write_bytes(b"old journal")

    def fail_replace(*args):
        raise PermissionError("simulated write refusal")

    monkeypatch.setattr("rpg_vkr.ui.workspace_tools.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        atomic_text(path, "новый журнал")
    assert path.read_bytes() == b"old journal"
    assert list(tmp_path.iterdir()) == [path]


def test_history_browsing_keeps_draft_and_limits_recent_actions(qt_app):
    edit = HistoryLineEdit()
    edit.set_history([f"команда {index}" for index in range(150)])
    edit.setText("черновик")
    QTest.keyClick(edit, Qt.Key.Key_Up)
    assert edit.text() == "команда 149"
    for _ in range(120):
        QTest.keyClick(edit, Qt.Key.Key_Up)
    assert edit.text() == "команда 50"
    for _ in range(100):
        QTest.keyClick(edit, Qt.Key.Key_Down)
    assert edit.text() == "черновик"
    edit.remember("новая команда")
    QTest.keyClick(edit, Qt.Key.Key_Up)
    assert edit.text() == "новая команда"
    edit.deleteLater()
