"""Exercise actual Qt signals and widgets without a desktop display."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


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
