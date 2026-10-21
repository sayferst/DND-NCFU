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

    def reveal(self, widget):
        self.stop()
        previous, self.last_page = self.last_page, widget
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
