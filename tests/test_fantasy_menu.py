"""Real modern menu, offline art and state-preserving navigation."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from rpg_vkr.application import Session
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_menu import MainMenu
from rpg_vkr.ui.main_window import MainWindow


@pytest.mark.parametrize("size", [(640, 620), (1280, 800), (1920, 1080)])
def test_modern_menu_art_buttons_keyboard_and_layout(qt_app, tmp_path, size):
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.resize(*size)
    window.show()
    qt_app.processEvents()
    try:
        menu = window.tabs.currentWidget()
        assert isinstance(menu, MainMenu) and not menu.art.isNull()
        assert [b.text() for b in menu.buttons] == [
            "Новая легенда",
            "Продолжить приключение",
            "Настройки",
            "О проекте",
        ]
        assert not window.scene_title.isVisible() and not window.resolution_panel.isVisible()
        assert all(menu.rect().contains(b.mapTo(menu, b.rect().center())) for b in menu.buttons)
        before = window._session.to_dict()
        menu.buttons[2].setFocus()
        QTest.keyClick(menu.buttons[2], Qt.Key.Key_Space)
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Настройки"
        assert window._session.to_dict() == before
    finally:
        window.close()


def test_continue_returns_to_active_hero_without_mutation(qt_app, tmp_path, monkeypatch):
    from rpg_vkr.domain.character import Character

    session = Session.create_hero(Character(name="Лея"), "scout", seed=42)
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window.show()
    qt_app.processEvents()
    try:
        window.action_input.setText("мой черновик")
        before = session.to_dict(), session.dice.checkpoint()
        window.resume_button.click()
        assert window.tabs.currentIndex() == 0 and window.scene_title.isVisible()
        window.open_section("Главное меню")
        assert window.action_input.text() == "мой черновик"
        assert (session.to_dict(), session.dice.checkpoint()) == before
    finally:
        window.action_input.clear()
        window.close()


def test_compact_calculations_reuse_same_widget_without_mutating_state(qt_app, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.resize(640, 620)
    window.show()
    window.resume_session()
    qt_app.processEvents()
    before = window._session.to_dict(), window._session.dice.checkpoint()
    observed = []

    def close_dialog():
        dialog = qt_app.activeModalWidget()
        observed.append(isinstance(dialog, QDialog) and window.resolution_panel.parent() is dialog)
        dialog.accept()

    try:
        assert window.compact_rolls.isVisible() and not window.resolution_panel.isVisible()
        QTimer.singleShot(20, close_dialog)
        window.compact_rolls.click()
        assert observed == [True] and not window.resolution_panel.isVisible()
        window.resize(1280, 800)
        qt_app.processEvents()
        assert window.resolution_panel.isVisible() and not window.compact_rolls.isVisible()
        assert before == (window._session.to_dict(), window._session.dice.checkpoint())
    finally:
        window.close()


def test_compact_chronicles_filters_and_expandable_card(qt_app, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QTextBrowser
    from response_cases import new_session

    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    window.resize(640, 620)
    window.show()
    window.open_section("Хроники мира")
    qt_app.processEvents()
    panel = window.chronicles_panel
    observed = []

    def close_dialog():
        dialog = qt_app.activeModalWidget()
        observed.append(bool(dialog.findChild(QTextBrowser).toPlainText()))
        dialog.accept()

    try:
        assert panel.compact_categories.isVisible() and not panel.categories.isVisible()
        assert panel.search.height() >= 28 and panel.state.height() >= 28
        panel.compact_categories.setCurrentIndex(1)
        assert panel.categories.currentRow() == 1
        QTimer.singleShot(20, close_dialog)
        panel.expand_card.click()
        assert observed == [True]
    finally:
        window.close()
