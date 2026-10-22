"""One dismissible notification, with persistent errors and optional short fades."""

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QPushButton, QVBoxLayout, QWidget

from rpg_vkr.ui.motion import system_reduced_motion


class Notifications(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("gameNotice")
        self.setStyleSheet(
            "QWidget#gameNotice {background:#182832; border:1px solid #b69b61; border-radius:8px;}"
        )
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        close = QPushButton("Понятно · закрыть")
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b"opacity", self)
        self.fade.setDuration(160)
        self.fade.finished.connect(lambda: self.hide() if self.effect.opacity() == 0 else None)
        self.hide()
        window.statusBar().messageChanged.connect(self.present)

    def present(self, text):
        if not text or not self.window.isVisible():
            return
        if getattr(self, "persistent", False) and self.isVisible():
            return  # A routine status update cannot erase an unread important error.
        self.timer.stop()
        self.persistent = any(
            word in text.casefold()
            for word in ("ошиб", "недоступ", "лимит", "не создан", "не удалось", "отмен", "отклон")
        )
        self.message.setText(text[:500])
        self.setFixedWidth(max(280, min(640, self.window.width() - 40)))
        self.adjustSize()
        self.move(
            (self.window.width() - self.width()) // 2,
            max(20, self.window.height() - self.height() - 50),
        )
        self.show()
        self.raise_()
        self.fade.stop()
        if self.window.animation_mode.currentIndex() != 2 and not system_reduced_motion():
            self.fade.setStartValue(0.2)
            self.fade.setEndValue(1)
            self.fade.start()
        else:
            self.effect.setOpacity(1)
        if not self.persistent:
            self.timer.start(7000)

    def dismiss(self):
        self.timer.stop()
        self.persistent = False
        self.fade.stop()
        if (
            self.isVisible()
            and self.window.animation_mode.currentIndex() != 2
            and not system_reduced_motion()
        ):
            self.fade.setStartValue(self.effect.opacity())
            self.fade.setEndValue(0)
            self.fade.start()
        else:
            self.hide()
