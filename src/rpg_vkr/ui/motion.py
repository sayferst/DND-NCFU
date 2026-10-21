"""Short interruptible snapshot fades; no timers repaint hidden pages or game RNG."""

import ctypes
import os

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

DURATION_MS = 180


def system_reduced_motion():
    if os.name == "nt":
        enabled = ctypes.c_int(1)
        try:
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return not bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return False


class Motion(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.overlay = None
        self.animation = None
        self.last_page = None

    def stop(self):
        if self.animation:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None
        if self.overlay:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None

    def reveal(self, widget, previous=None):
        self.stop()
        previous, self.last_page = previous or self.last_page, widget
        mode = getattr(self.window, "animation_mode", None)
        if (mode and mode.currentIndex() == 2) or system_reduced_motion() or not widget.isVisible():
            return
        # Only fade a snapshot. The live page stays usable even during fast switching.
        if previous is None or previous is widget:
            return
        snapshot = previous.grab()
        if snapshot.isNull():
            return
        self.overlay = QLabel(widget)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setPixmap(snapshot)
        self.overlay.setGeometry(widget.rect())
        effect = QGraphicsOpacityEffect(self.overlay)
        self.overlay.setGraphicsEffect(effect)
        self.overlay.show()
        self.animation = QPropertyAnimation(effect, b"opacity", self)
        self.animation.setDuration(100 if mode and mode.currentIndex() == 1 else DURATION_MS)
        self.animation.setStartValue(0.45)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.stop)
        self.animation.start()


class ButtonGlow(QObject):
    """One short hover effect per button, idle when hidden or outside the pointer."""

    def __init__(self, button, window):
        super().__init__(button)
        self.button, self.window = button, window
        self.glow = QLabel(button)
        self.glow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.glow.setStyleSheet(
            "background:transparent; border:1px solid #d8b578; border-radius:6px;"
        )
        self.effect = QGraphicsOpacityEffect(self.glow)
        self.glow.setGraphicsEffect(self.effect)
        self.effect.setOpacity(0)
        self.animation = QPropertyAnimation(self.effect, b"opacity", self)
        self.animation.setDuration(120)
        self.animation.finished.connect(self.finished)
        self.glow.hide()
        button.installEventFilter(self)

    def finished(self):
        if self.effect.opacity() == 0:
            self.glow.hide()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        from shiboken6 import isValid

        if not all(
            isValid(obj)
            for obj in (self.window, self.window.animation_mode, self.glow, self.animation)
        ):
            return False

        mode = self.window.animation_mode.currentIndex()
        if event.type() == QEvent.Type.Hide or mode == 2 or system_reduced_motion():
            self.animation.stop()
            self.glow.hide()
            return False
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave) and self.button.isEnabled():
            self.animation.stop()
            self.glow.setGeometry(self.button.rect())
            self.glow.show()
            self.animation.setStartValue(self.effect.opacity())
            self.animation.setEndValue(0.6 if event.type() == QEvent.Type.Enter else 0)
            self.animation.start()
        return False
