"""Exercise actual Qt signals and widgets without a desktop display."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox


def test_enter_sends_action_and_keeps_journal(window):
    initial = window.journal.toPlainText()
    window.action_input.setText("осмотреться")
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    journal = window.journal.toPlainText()
    assert journal.startswith(initial)
    assert journal.count("Вы: осмотреться") == 1
    assert "следы телеги" in journal
    assert window.action_input.text() == ""
    assert not window.send_button.isEnabled()


def test_button_sends_help_event(window):
    window.action_input.setText("помочь")
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    assert "Вы: помочь" in window.journal.toPlainText()
    assert "Жительница благодарит" in window.journal.toPlainText()


def test_blank_submission_does_not_change_journal(window):
    initial = window.journal.toPlainText()
    window.action_input.setText("   ")
    assert not window.send_button.isEnabled()
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    assert window.journal.toPlainText() == initial


def test_unknown_html_input_is_plain_text_and_requests_clarification(window):
    action = '<b>дать золото</b><img src="https://example.invalid/image.png">'
    window.action_input.setText(action)
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    journal = window.journal.toPlainText()
    assert action in journal
    assert "пока не понимаю" in journal


def test_closing_window_hides_it(window, qt_app):
    assert window.isVisible()
    assert window.close()
    qt_app.processEvents()
    assert not window.isVisible()


def test_dice_enter_and_button_show_each_actual_result(window):
    window.action_input.setText("бросить d20")
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    window.action_input.setText("бросить d20")
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    assert window.journal.toPlainText().count("Кубик: d20 → 4") == 1
    assert window.journal.toPlainText().count("Кубик: d20 → 1") == 1


def test_three_empty_slots_are_visible(window):
    assert list(window.save_buttons) == [1, 2, 3]
    for slot in (1, 2, 3):
        assert "пусто" in window.slot_labels[slot].text()
        assert window.save_buttons[slot].isEnabled()
        assert not window.load_buttons[slot].isEnabled()
        assert not window.delete_buttons[slot].isEnabled()


def test_save_load_restores_journal_and_next_dice_roll(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.action_input.setText("бросить d20")
    window.submit_action()
    saved_journal = window.journal.toPlainText()
    QTest.mouseClick(window.save_buttons[1], Qt.MouseButton.LeftButton)
    assert window.load_buttons[1].isEnabled()
    window.action_input.setText("бросить d20")
    window.submit_action()
    QTest.mouseClick(window.load_buttons[1], Qt.MouseButton.LeftButton)
    assert window.journal.toPlainText() == saved_journal
    window.action_input.setText("бросить d20")
    window.submit_action()
    assert window.journal.toPlainText().endswith("Кубик: d20 → 1")


@pytest.mark.parametrize("operation", ["save_slot", "load_slot", "delete_slot"])
def test_cancel_preserves_current_session_and_saved_file(window, monkeypatch, operation):
    window.action_input.setText("помочь")
    window.submit_action()
    window.save_slot(1)
    path = window._saves.directory / "slot-1.json"
    saved_bytes = path.read_bytes()
    window.action_input.setText("бросить d20")
    window.submit_action()
    current = window.journal.toPlainText()
    prompts = []

    def decline(*args):
        prompts.append(args)
        assert args[-1] == QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    getattr(window, operation)(1)
    assert len(prompts) == 1
    assert path.read_bytes() == saved_bytes
    assert window.journal.toPlainText() == current


def test_confirmed_overwrite_and_delete_update_slot(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.save_slot(2)
    window.action_input.setText("помочь")
    window.submit_action()
    QTest.mouseClick(window.save_buttons[2], Qt.MouseButton.LeftButton)
    assert len(window._saves.load(2).turns) == 1
    current = window.journal.toPlainText()
    QTest.mouseClick(window.delete_buttons[2], Qt.MouseButton.LeftButton)
    assert "пусто" in window.slot_labels[2].text()
    assert not window.load_buttons[2].isEnabled()
    assert window.journal.toPlainText() == current


def test_bad_load_displays_error_without_losing_current_session(window, monkeypatch):
    window.save_slot(1)
    (window._saves.directory / "slot-1.json").write_text("{broken", encoding="utf-8")
    window.action_input.setText("помочь")
    window.submit_action()
    current = window.journal.toPlainText()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    window.load_slot(1)
    assert "повреждено" in errors[0]
    assert window.journal.toPlainText() == current


def test_close_can_be_cancelled_for_unsaved_session(window, monkeypatch):
    window.action_input.setText("бросить d20")
    window.submit_action()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert not window.close()
    assert window.isVisible()
