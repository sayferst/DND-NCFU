"""Verify a save off the GUI thread while keeping the synchronous menu contract."""

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout


class SaveReader(QThread):
    def __init__(self, saves, slot, parent):
        super().__init__(parent)
        self.saves, self.slot = saves, slot
        self.session = self.error = None

    def run(self):
        try:
            self.session = self.saves.load(self.slot)
        except Exception as error:
            self.error = error


class LoadDialog(QDialog):
    def reject(self):
        # Closing a running QThread can terminate the application. The operation
        # is read-only and must finish before its worker can be destroyed.
        if not self.reader.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.reader.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)


def read_with_progress(parent, saves, slot):
    dialog = LoadDialog(parent)
    dialog.setWindowTitle("Загрузка кампании")
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(390)
    layout = QVBoxLayout(dialog)
    label = QLabel(
        "Проверяем сохранение и восстанавливаем ход событий.\n"
        "Большой кампании потребуется больше времени."
    )
    label.setWordWrap(True)
    layout.addWidget(label)
    progress = QProgressBar()
    progress.setRange(0, 0)
    layout.addWidget(progress)
    dialog.reader = reader = SaveReader(saves, slot, dialog)
    reader.finished.connect(dialog.accept)
    reader.start()
    try:
        dialog.exec()
        reader.wait()
        if reader.error is not None:
            raise reader.error
        return reader.session
    finally:
        reader.wait()
        dialog.deleteLater()
