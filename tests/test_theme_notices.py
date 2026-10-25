"""Menu-only in-flow notices and readable real Qt controls across both themes."""

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QLineEdit, QPushButton, QToolButton

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow


def luminance(color):
    values = [color.redF(), color.greenF(), color.blueF()]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def contrast(front, back):
    values = sorted((luminance(front), luminance(back)))
    return (values[1] + 0.05) / (values[0] + 0.05)


@pytest.mark.parametrize("theme", ["Светлая", "Тёмная"])
def test_controls_and_menu_notice_have_readable_contrast(qt_app, tmp_path, theme):
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.show()
    try:
        window.animation_mode.setCurrentIndex(2)
        window.theme_choice.setCurrentText(theme)
        window.statusBar().showMessage("Ошибка подключения: хост недоступен")
        qt_app.processEvents()
        notice = window.notifications
        assert notice.menu.isAncestorOf(notice) and notice.isVisible()
        assert (
            contrast(
                notice.message.palette().color(QPalette.ColorRole.WindowText),
                notice.palette().color(QPalette.ColorRole.Window),
            )
            >= 4.5
        )
        for cls, front, back in (
            (QLabel, QPalette.ColorRole.WindowText, QPalette.ColorRole.Window),
            (QLineEdit, QPalette.ColorRole.Text, QPalette.ColorRole.Base),
            (QDoubleSpinBox, QPalette.ColorRole.Text, QPalette.ColorRole.Base),
            (QPushButton, QPalette.ColorRole.ButtonText, QPalette.ColorRole.Button),
            (QToolButton, QPalette.ColorRole.ButtonText, QPalette.ColorRole.Button),
        ):
            widget = cls(window)
            widget.ensurePolished()
            background = widget.palette().color(back)
            if background.alpha() == 0:
                background = window.palette().color(QPalette.ColorRole.Window)
            assert contrast(widget.palette().color(front), background) >= 4.5
            widget.setEnabled(False)
            widget.ensurePolished()
            palette = widget.palette()
            background = palette.color(QPalette.ColorGroup.Disabled, back)
            if background.alpha() == 0:
                background = window.palette().color(QPalette.ColorRole.Window)
            assert contrast(palette.color(QPalette.ColorGroup.Disabled, front), background) >= 4.5
            widget.deleteLater()
        window.open_section("Настройки")
        assert not notice.isVisible() and not window.scene_title.isVisible()
        window.open_section("Главное меню")
        assert notice.isVisible()
        notice.dismiss()
        assert not notice.isVisible()
    finally:
        window.close()
