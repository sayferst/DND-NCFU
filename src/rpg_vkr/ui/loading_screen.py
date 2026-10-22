"""A lightweight animated fantasy launch screen; progress comes from actual startup work."""

import math

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from rpg_vkr.build_info import DISPLAY_NAME, VERSION
from rpg_vkr.resources import resource_path


class StartupWorker(QThread):
    progress = Signal(int, str)
    ready = Signal()
    failed = Signal(object)

    def run(self):
        try:
            from rpg_vkr.self_check import check_resources

            check_resources(lambda value, text: self.progress.emit(value, text))
            self.ready.emit()
        except Exception as error:
            self.failed.emit(error)


class LoadingScreen(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(DISPLAY_NAME)
        self.resize(900, 560)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(900, screen.width() - 40), min(560, screen.height() - 40))
        self.move(screen.center() - self.rect().center())
        self.background = QPixmap(str(resource_path("rpg_vkr/ui/assets/kingdom.png")))
        self.emblem = QPixmap(str(resource_path("rpg_vkr/ui/assets/DND-NCFU.png")))
        self.value = 0
        self.label = "Пробуждение королевств"
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(33)

    def set_stage(self, value, label):
        self.value = max(self.value, min(100, value))
        self.label = label
        self.update()

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.elapsed.elapsed() / 1000
        area = self.rect()
        p.fillRect(area, QColor("#10202b"))
        if not self.background.isNull():
            image = self.background
            scale = max(self.width() / image.width(), self.height() / image.height()) * 1.05
            w, h = image.width() * scale, image.height() * scale
            p.drawPixmap(
                QRectF(
                    (self.width() - w) / 2 + math.sin(t * 0.15) * 8, (self.height() - h) / 2, w, h
                ),
                image,
                QRectF(image.rect()),
            )
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(5, 15, 24, 35))
        shade.setColorAt(0.6, QColor(5, 15, 24, 80))
        shade.setColorAt(1, QColor(5, 15, 24, 240))
        p.fillRect(area, shade)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(42):
            x = (i * 83.7 + math.sin(t * 0.4 + i) * 18) % self.width()
            y = self.height() - ((i * 59.3 + t * (7 + i % 9)) % self.height())
            alpha = int(60 + 90 * (0.5 + 0.5 * math.sin(t * 1.1 + i)))
            p.setBrush(QColor(237, 191, 105, alpha))
            p.drawEllipse(QRectF(x, y, 2 + i % 3, 2 + i % 3))
        p.drawPixmap(
            QRectF(self.width() / 2 - 42, self.height() * 0.43 - 42, 84, 84),
            self.emblem,
            QRectF(self.emblem.rect()),
        )
        p.setPen(QColor("#edd6a7"))
        p.setFont(QFont("Georgia", 22))
        p.drawText(
            QRectF(20, self.height() * 0.59, self.width() - 40, 45),
            Qt.AlignmentFlag.AlignCenter,
            "Хроники забытых королевств",
        )
        bar = QRectF(self.width() * 0.23, self.height() - 75, self.width() * 0.54, 9)
        p.setBrush(QColor("#152c35"))
        p.drawRoundedRect(bar, 4, 4)
        p.setBrush(QColor("#d5b469"))
        p.drawRoundedRect(
            QRectF(bar.x(), bar.y(), bar.width() * self.value / 100, bar.height()), 4, 4
        )
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(
            QRectF(20, self.height() - 57, self.width() - 40, 25),
            Qt.AlignmentFlag.AlignCenter,
            self.label,
        )
        p.setPen(QColor("#aeb8b7"))
        p.drawText(QRectF(12, 10, 150, 24), Qt.AlignmentFlag.AlignLeft, "DND-NCFU " + VERSION)
        p.end()
