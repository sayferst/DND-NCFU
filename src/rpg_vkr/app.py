"""Launch the prototype's Qt event loop."""

import sys

from PySide6.QtWidgets import QApplication

from rpg_vkr.ui.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("DND-NCFU")
    window = MainWindow()
    window.show()
    return app.exec()
