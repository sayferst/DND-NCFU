"""A local fantasy backdrop for an explicit, cancellable world-creation request."""

import math
import random

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from rpg_vkr.resources import resource_path

PHRASES = (
    "Пробуждаем древние королевства…",
    "Зажигаем огни в далёких городах…",
    "Знакомим мир с его будущими героями…",
    "Прячем тайны в забытых подземельях…",
    "Наполняем лавки редкостями…",
    "Прокладываем тропы к неизвестному…",
    "Шепчемся с хранителями леса…",
    "Вплетаем судьбы жителей в историю…",
    "Наносим на карты неизведанные земли…",
    "Открываем двери навстречу приключению…",
)


class WorldCreationScreen(QWidget):
    start_requested = Signal()
    cancel_requested = Signal()
    menu_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("worldCreationScreen")
        self.atlas = QPixmap(str(resource_path("rpg_vkr/ui/assets/world-creation-atlas.png")))
        self.state = "ready"
        self.session = None
        self._random = random.Random()
        self._phrase_index = -1
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.animate)
        self._last_phrase = -1
        self.setStyleSheet("""
            QWidget#worldCreationScreen QLabel { background: transparent; color: #eddfc4; }
            QWidget#worldCreationScreen QPushButton {
                background: rgba(18, 34, 43, 225); color: #f4e1b4;
                border: 1px solid #b69b61; border-radius: 7px;
                font-size: 17px; padding: 12px 26px;
            }
            QWidget#worldCreationScreen QPushButton:hover { background: #32494e; }
            QWidget#worldCreationScreen QPushButton:disabled { color: #8b9795; }
            QWidget#worldCreationScreen QProgressBar {
                background: rgba(8, 20, 28, 220); border: 1px solid #8e7950;
                border-radius: 6px; min-height: 12px; max-height: 12px;
            }
            QWidget#worldCreationScreen QProgressBar::chunk {
                background: #d6b36d; border-radius: 5px; width: 110px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 32, 28, 30)
        layout.setSpacing(16)
        self.brand = self.label("ХРОНИКИ ЗАБЫТЫХ КОРОЛЕВСТВ", 12)
        layout.addWidget(self.brand, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(3)
        self.title = self.label("Ваша новая легенда", 32, "Georgia")
        self.hero = self.label("", 17)
        self.detail = self.label("", 12)
        self.detail.setMaximumWidth(760)
        for item in (self.title, self.hero, self.detail):
            layout.addWidget(item, 0, Qt.AlignmentFlag.AlignHCenter)
        self.create_button = QPushButton("Создать новый мир")
        self.create_button.setMinimumWidth(300)
        self.create_button.setMinimumHeight(54)
        self.create_button.clicked.connect(self.start_requested)
        layout.addWidget(self.create_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(3)
        self.flavor = self.label("", 17, "Georgia")
        self.stage = self.label("", 11)
        layout.addWidget(self.flavor, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(960)
        layout.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignHCenter)
        self.cancel_button = QPushButton("Отменить создание")
        self.cancel_button.clicked.connect(self.cancel_requested)
        layout.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.menu_button = QPushButton("Вернуться в меню")
        self.menu_button.clicked.connect(self.menu_requested)
        layout.addWidget(self.menu_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.prepare(None)

    @staticmethod
    def label(text, size, family="Segoe UI"):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont(family, size))
        label.setMinimumHeight(label.fontMetrics().height() + 8)
        return label

    def prepare(self, session, error=""):
        self.session = session
        self.state = "error" if error else "ready"
        self.title.setText("Не удалось создать мир" if error else "Ваша новая легенда")
        self.hero.setText(session.character.name if session else "")
        self.detail.setText(error or "Герой готов. Создайте мир, в котором начнётся ваша история.")
        self.create_button.setText("Повторить создание мира" if error else "Создать новый мир")
        self.create_button.setVisible(True)
        self.create_button.setEnabled(bool(session and session.progress.enabled))
        self.menu_button.setVisible(True)
        for widget in (self.progress, self.flavor, self.stage, self.cancel_button):
            widget.hide()
        self.update()

    def begin(self, session):
        if self.state == "busy" and self.session is session:
            return
        self.session = session
        self.state = "busy"
        self.elapsed.restart()
        self._last_phrase = -1
        self.title.setText("Рождение нового мира")
        self.hero.setText("Для героя «" + session.character.name + "»")
        self.detail.setText("Мастер воплощает вашу анкету и пожелания в новую историю.")
        self.create_button.hide()
        self.create_button.setEnabled(False)
        self.menu_button.hide()
        self.stage.setText("Мастер создаёт мир. Это может занять несколько минут.")
        self.progress.setRange(0, 0)
        for widget in (self.progress, self.flavor, self.stage, self.cancel_button):
            widget.show()
        self.animate()

    def complete(self):
        self.state = "success"
        self.title.setText("Мир создан")
        self.detail.setText("Ваша история начинается…")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.flavor.setText("Добро пожаловать в новую легенду")
        self.stage.setText("Мир проверен. Открываем первую страницу истории.")
        self.cancel_button.hide()
        self.update()

    def animate(self):
        period = self.elapsed.elapsed() // 4200
        if self.state == "busy" and period != self._last_phrase:
            choices = [i for i in range(len(PHRASES)) if i != self._phrase_index]
            self._phrase_index = self._random.choice(choices)
            self.flavor.setText(PHRASES[self._phrase_index])
            self._last_phrase = period
        self.update()

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self.title.setFont(QFont("Georgia", 23 if self.width() < 800 else 34))
        for label in (self.brand, self.title, self.hero, self.detail, self.flavor, self.stage):
            label.setFixedWidth(min(760 if label is self.detail else 1000, self.width() - 56))
            label.setMinimumHeight(label.fontMetrics().height() + 8)
        self.progress.setFixedWidth(max(260, min(960, self.width() - 80)))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        seconds = self.elapsed.elapsed() / 1000
        painter.fillRect(self.rect(), QColor("#0b1720"))
        if not self.atlas.isNull():
            panel_height = self.atlas.height() / 3
            phase = seconds / 9
            current = int(phase) % 3
            blend = min(1.0, (phase % 1) / 0.2)
            for panel, opacity in (((current - 1) % 3, 1.0), (current, blend)):
                scale = max(self.width() / self.atlas.width(), self.height() / panel_height)
                crop_width, crop_height = self.width() / scale, self.height() / scale
                source = QRectF(
                    (self.atlas.width() - crop_width) * (0.35 + math.sin(seconds * 0.06) * 0.1),
                    panel * panel_height + (panel_height - crop_height) / 2,
                    crop_width,
                    crop_height,
                )
                painter.setOpacity(opacity)
                painter.drawPixmap(QRectF(self.rect()), self.atlas, source)
        painter.setOpacity(1)
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(4, 12, 20, 100))
        shade.setColorAt(0.5, QColor(4, 12, 20, 140))
        shade.setColorAt(1, QColor(4, 12, 20, 245))
        painter.fillRect(self.rect(), shade)
        painter.end()
