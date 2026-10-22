"""State-preserving visible tabs and interruptible motion on the real modern window."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from response_cases import new_session

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow


def test_visible_tabs_keep_draft_rng_and_scroll_with_fast_keyboard_changes(qt_app, tmp_path):
    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    window.resize(640, 620)
    window.show()
    try:
        window.open_section("Приключение")
        window.action_input.setText("сохранённый черновик")
        before = window._session.to_dict(), window._session.dice.checkpoint()
        tabs = window.section_tabs
        assert tabs.isVisible() and not window.navigation.isVisible()
        assert all(
            tabs.tabText(i) not in {"Мастер", "Художник", "Разработчик"}
            for i in range(tabs.count())
        )
        tabs.setFocus()
        for _ in range(8):
            QTest.keyClick(tabs, Qt.Key.Key_Right)
            qt_app.processEvents()
        window.open_section("Приключение")
        assert window.action_input.text() == "сохранённый черновик"
        assert before == (window._session.to_dict(), window._session.dice.checkpoint())
        window.animation_mode.setCurrentIndex(2)
        window.open_section("Герой")
        assert window.motion.animation is None and window.motion.overlay is None
        window.open_section("Приключение")
    finally:
        window.action_input.clear()
        window.close()


def test_disabled_motion_and_persistent_notice(qt_app, tmp_path):
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.show()
    try:
        window.animation_mode.setCurrentIndex(2)
        window.show_world_creation()
        qt_app.processEvents()
        assert not window.world_creation_screen.timer.isActive()
        window.open_section("Приключение")
        window.statusBar().showMessage("Ошибка сети: мастер недоступен")
        notice = window.notifications
        assert notice.isVisible() and notice.persistent and not notice.timer.isActive()
        window.statusBar().showMessage("Сохранено")
        assert "Ошибка" in notice.message.text()
        notice.dismiss()
        assert not notice.isVisible()
        assert all(not glow.animation.state().value for glow in window.button_glows)
    finally:
        window.close()
