"""Automated widget checks use Qt's offscreen platform, including on Windows."""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from rpg_vkr.application import Session
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.main_window import MainWindow

    widget = MainWindow(
        session=Session(seed=42), saves=SaveSlots(tmp_path / "saves"), legacy_controls=True
    )
    widget.director_mode.setChecked(False)  # Legacy transport regression suite.
    widget.show()
    qt_app.processEvents()
    yield widget
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()
