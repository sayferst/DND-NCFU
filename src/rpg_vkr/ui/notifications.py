"""One dismissible notification, with persistent errors and optional short fades."""

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QPushButton, QVBoxLayout

from rpg_vkr.ui.motion import system_reduced_motion


class Notifications(QFrame):
    def __init__(self, window):
        menu = next(
            window.tabs.widget(i)
            for i in range(window.tabs.count())
            if window.tabs.tabText(i) == "Главное меню"
        )
        super().__init__(menu)
        self.menu = menu
        self.window = window
        self.setObjectName("gameNotice")
        self.setStyleSheet(
            "QFrame#gameNotice {background:#182832; color:#e6dfcf; "
            "border:1px solid #b69b61; border-radius:8px;} "
            "QFrame#gameNotice QLabel {color:#e6dfcf; background:transparent;} "
            "QFrame#gameNotice QPushButton {background:#223038; color:#f0dfbc; "
            "border:1px solid #86714d; border-radius:5px; padding:6px;}"
        )
        self.setMaximumWidth(640)
        self.menu.notice_layout.addWidget(self, 0, Qt.AlignmentFlag.AlignHCenter)
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
        window.tabs.currentChanged.connect(self.sync)

    def sync(self, *_):
        self.setVisible(self.window.tabs.currentWidget() is self.menu and bool(self.message.text()))
        if self.isVisible() and getattr(self, "persistent", False):
            QTimer.singleShot(0, lambda: self.menu.scroll.ensureWidgetVisible(self))

    def fit(self):
        width = max(240, min(640, self.menu.scroll.viewport().width() - 64))
        self.setFixedWidth(width)
        self.message.setMinimumHeight(
            max(self.message.fontMetrics().lineSpacing(), self.message.heightForWidth(width - 40))
            + 6
        )

    def present(self, text):
        if not text or not self.window.isVisible():
            return
        if getattr(self, "persistent", False) and self.message.text():
            return  # A routine status update cannot erase an unread important error.
        self.timer.stop()
        self.persistent = any(
            word in text.casefold()
            for word in ("ошиб", "недоступ", "лимит", "не создан", "не удалось", "отмен", "отклон")
        )
        self.message.setText(text[:500])
        self.fit()
        self.sync()
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
        important = getattr(self, "persistent", False)
        self.persistent = False
        self.message.clear()
        if important:
            self.menu.scroll.verticalScrollBar().setValue(0)
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
