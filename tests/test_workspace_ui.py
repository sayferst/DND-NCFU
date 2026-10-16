"""Integrated navigation, reading settings, shortcuts and file operations in real Qt."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from rpg_vkr.application import Session
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.ui.workspace_tools import ReadingPreferences, load_preferences


def test_tabs_and_quest_follow_actual_world(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Приключение",
        "Герой",
        "Инвентарь",
        "Задание",
        "Команды",
        "Настройки",
        "Сохранения",
        "Главное меню",
        "Карта",
        "Жители",
        "Лавка",
        "Кубики",
        "Как играть",
        "Схватка",
    ]
    assert window.quest_progress.value() == 0
    window.quest_action.click()
    assert window._session.world.basket == 1
    assert window.quest_progress.value() == 1
    window._run_command("идти на рынок")
    window.quest_action.click()
    assert window.quest_progress.value() == 2
    assert not window.quest_action.isEnabled()
    assert "завершено" in window.quest_label.text()


def test_reference_filters_and_inserts_without_executing(window):
    before = window._session.to_dict()
    window.command_search.setText("продать бинт")
    assert window.command_list.currentItem().data(Qt.ItemDataRole.UserRole) == "продать бинт"
    window.insert_command_button.click()
    assert window.action_input.text() == "продать бинт"
    assert window._session.to_dict() == before
    window.command_search.setText("невозможная команда")
    assert not window.insert_command_button.isEnabled()


def test_reference_replacement_can_be_cancelled(window, monkeypatch):
    window.action_input.setText("мой черновик")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.insert_command_button.click()
    assert window.action_input.text() == "мой черновик"
    assert not window._session.turns


def test_history_restores_from_slot_and_keeps_unsubmitted_draft(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._run_command("проверить силу")
    window.save_slot(1)
    window._run_command("бросить d20")
    window.load_slot(1)
    window.action_input.setText("черновик")
    QTest.keyClick(window.action_input, Qt.Key.Key_Up)
    assert window.action_input.text() == "проверить силу"
    QTest.keyClick(window.action_input, Qt.Key.Key_Down)
    assert window.action_input.text() == "черновик"


def test_quick_save_selects_slot_then_confirms_overwrite(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][1], True))
    window.quick_save()
    path = window._saves.directory / "slot-2.json"
    assert path.exists()
    assert "Ячейка 2" in window.session_status.text()
    assert "активная" in window.slot_labels[2].text()
    saved = path.read_bytes()
    window._run_command("бросить d20")
    assert "есть изменения" in window.session_status.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.quick_save()
    assert path.read_bytes() == saved
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.quick_save()
    assert "без изменений" in window.session_status.text()
    assert len(window._saves.load(2).turns) == 1
    window.delete_slot(2)
    assert "Без ячейки" in window.session_status.text()
    assert "есть изменения" in window.session_status.text()


def test_choose_load_and_cancel_save_do_not_modify_other_slots(window, monkeypatch):
    window._saves.save(3, Session(seed=18))
    before = (window._saves.directory / "slot-3.json").read_bytes()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][0], False))
    window.quick_save()
    assert window._current_slot is None
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][0], True))
    window.choose_load()
    assert window._current_slot == 3
    assert (window._saves.directory / "slot-3.json").read_bytes() == before
    assert not (window._saves.directory / "slot-1.json").exists()


def test_find_wraps_and_reports_no_match_without_changing_journal(window):
    window._run_command("помочь")
    before = window.journal.toPlainText()
    window.journal_search.setText("Жительница")
    window.find_in_journal()
    assert window.journal.textCursor().selectedText().casefold() == "жительница"
    window.find_in_journal()
    assert window.journal.textCursor().selectedText().casefold() == "жительница"
    window.journal_search.setText("невозможная строка")
    window.find_in_journal()
    assert "не найдено" in window.statusBar().currentMessage()
    assert window.journal.toPlainText() == before


def test_reading_preferences_persist_without_touching_slot_or_game(window, qt_app):
    window.save_slot(1)
    path = window._saves.directory / "slot-1.json"
    saved = path.read_bytes()
    before = window._session.to_dict()
    window.font_size.setValue(17)
    window.theme_choice.setCurrentText("Тёмная")
    assert window.journal.font().pointSize() == 17
    assert load_preferences(window._preferences_path) == (ReadingPreferences(17, "Тёмная"), "")
    reopened = MainWindow(saves=window._saves)
    try:
        assert reopened.journal.font().pointSize() == 17
        assert reopened.theme_choice.currentText() == "Тёмная"
        assert window._session.to_dict() == before
        assert path.read_bytes() == saved
        assert not window._dirty
        reopened._reset_reading()
        assert reopened.font_size.value() == 13
        assert reopened.theme_choice.currentText() == "Системная"
    finally:
        reopened.close()
        reopened.deleteLater()
        qt_app.processEvents()


def test_preferences_write_failure_is_visible_and_game_kept(window, monkeypatch):
    def fail(*args):
        raise PermissionError("simulated")

    monkeypatch.setattr("rpg_vkr.ui.workspace_panel.save_preferences", fail)
    before = window._session.to_dict()
    window.font_size.setValue(15)
    assert window.journal.font().pointSize() == 15
    assert "не сохранены" in window.preferences_status.text()
    assert window._session.to_dict() == before


def test_export_is_utf8_plain_text_and_does_not_mark_session_saved(window, tmp_path, monkeypatch):
    window._run_command("помочь")
    path = tmp_path / "экспорт.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_journal()
    assert path.read_text(encoding="utf-8") == window.journal.toPlainText() + "\n"
    assert window._dirty
    assert not window._saves.directory.exists()


@pytest.mark.parametrize("target", ["saves/slot-1.json", "reading.json"])
def test_export_cannot_overwrite_internal_data(window, monkeypatch, target):
    window.save_slot(1)
    path = window._saves.directory.parent / target
    before = path.read_bytes() if path.exists() else None
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window.export_journal()
    assert warnings
    assert (path.read_bytes() if path.exists() else None) == before


def test_export_cancel_keeps_game_and_files(window, tmp_path, monkeypatch):
    before = window._session.to_dict()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    window.export_journal()
    assert window._session.to_dict() == before
    assert not list(tmp_path.iterdir())


def test_ctrl_s_and_ctrl_f_work_across_tabs(window, qt_app, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][0], True))
    window.tabs.setCurrentIndex(1)
    window.activateWindow()
    qt_app.processEvents()
    QTest.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    qt_app.processEvents()
    assert (window._saves.directory / "slot-1.json").exists()
    QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    qt_app.processEvents()
    assert window.tabs.currentIndex() == 0
    assert window.journal_search.hasFocus()


def test_export_error_preserves_session_and_old_output(window, tmp_path, monkeypatch):
    path = tmp_path / "journal.txt"
    path.write_text("старый журнал", encoding="utf-8")
    window._run_command("помочь")
    before = window._session.to_dict()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))

    def fail(*args):
        raise PermissionError("simulated refusal")

    monkeypatch.setattr("rpg_vkr.ui.workspace_tools.os.replace", fail)
    window.export_journal()
    assert errors
    assert window._session.to_dict() == before
    assert window._dirty
    assert path.read_text(encoding="utf-8") == "старый журнал"


def test_empty_quick_load_reports_without_opening_a_dialog(window, monkeypatch):
    def unexpected(*args):
        raise AssertionError("No selection is needed for empty slots")

    monkeypatch.setattr(QInputDialog, "getItem", unexpected)
    window.choose_load()
    assert "нет сохранённых" in window.statusBar().currentMessage()
    assert not window._session.turns


def test_compact_window_keeps_journal_and_controls_visible(window, qt_app):
    window.resize(640, 620)
    window.font_size.setValue(20)
    qt_app.processEvents()
    assert window.journal.height() >= 160
    assert window.action_input.isVisible()
    assert window.send_button.isVisible()
    assert window.journal_search.isVisible()
    window.tabs.setCurrentIndex(6)
    qt_app.processEvents()
    assert all(button.isVisible() for button in window.save_buttons.values())


def test_bad_preferences_startup_reports_fallback_and_keeps_bytes(window, qt_app):
    window._preferences_path.write_text("{broken", encoding="utf-8")
    reopened = MainWindow(saves=window._saves)
    try:
        assert reopened.font_size.value() == 13
        assert "стандартные" in reopened.preferences_status.text()
        assert window._preferences_path.read_text(encoding="utf-8") == "{broken"
    finally:
        reopened.close()
        reopened.deleteLater()
        qt_app.processEvents()
