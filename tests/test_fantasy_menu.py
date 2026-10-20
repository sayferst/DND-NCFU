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
