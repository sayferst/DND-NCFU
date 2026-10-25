"""Original offline menu art and existing session navigation."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

BACKGROUND = Path(__file__).with_name("assets") / "kingdom.png"
BUTTON_STYLE = """
    QPushButton { background: #223038; color: #f0dfbc; border: 1px solid #86714d;
        border-radius: 5px; font-size: 16px; padding: 8px 20px; }
    QPushButton:hover { background: #36464b; border-color: #efd29b; }
    QPushButton:pressed { background: #14222b; }
    QPushButton:focus { border: 2px solid #ffe3ab; }
"""


class MainMenu(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("legendMenu")
        self.art = QPixmap(str(BACKGROUND))
        self._scaled = QPixmap()
        self._scaled_size = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("menuScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("menuScrollViewport")
        content = QWidget()
        content.setObjectName("legendMenuContent")
        self.scroll.setWidget(content)
        self.scroll.setStyleSheet(
            "QScrollArea#menuScroll, QWidget#menuScrollViewport, QWidget#legendMenuContent "
            "{ background: transparent; border: none; }"
        )
        self.scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        layout.addStretch(2)
        self.title = QLabel("DND-NCFU")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("color: #f4dfb7; background: transparent; letter-spacing: 7px;")
        layout.addWidget(self.title)
        subtitle = QLabel("ХРОНИКИ ЗАБЫТЫХ КОРОЛЕВСТВ")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #c9bb9d; font-size: 12px; letter-spacing: 2px;")
        layout.addWidget(subtitle)
        ornament = QLabel("──────────  ◇  ──────────")
        ornament.setStyleSheet("color: #ba9961; background: transparent;")
        ornament.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ornament)
        panel = QFrame()
        panel.setMaximumWidth(420)
        panel.setMinimumWidth(360)
        panel.setStyleSheet(
            "QFrame { background: rgba(9, 20, 27, 210); "
            "border: 1px solid #6c5e45; border-radius: 12px; }"
        )
        buttons = QVBoxLayout(panel)
        self.actions = buttons
        buttons.setContentsMargins(24, 22, 24, 22)
        buttons.setSpacing(12)
        self.buttons = []
        for text, callback in (
            ("Новая легенда", window.new_character),
            ("Продолжить приключение", lambda: continue_adventure(window)),
            ("Настройки", lambda: window.open_section("Настройки")),
            ("О проекте", window._show_about),
        ):
            button = QPushButton(text)
            button.setMinimumHeight(42)
            button.setStyleSheet(BUTTON_STYLE)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            self.buttons.append(button)
        window.resume_button = self.buttons[1]
        self.menu_actions = {}
        for name in ("Сохранения", "Фотоальбом"):
            action = QPushButton(name)
            action.clicked.connect(lambda checked=False, section=name: window.open_section(section))
            self.add_menu_action(action)
            self.menu_actions[name] = action
        layout.addWidget(panel, 0, Qt.AlignmentFlag.AlignHCenter)
        window.home_summary = QLabel()
        window.home_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        window.home_summary.setWordWrap(True)
        window.home_summary.setMaximumWidth(520)
        window.home_summary.setMinimumWidth(360)
        window.home_summary.setMinimumHeight(38)
        window.home_summary.setStyleSheet(
            "color: #b8c2c4; font-size: 11px; background: transparent;"
        )
        layout.addWidget(window.home_summary, 0, Qt.AlignmentFlag.AlignHCenter)
        self.notice_layout = QVBoxLayout()
        layout.addLayout(self.notice_layout)
        exit_button = QPushButton("Покинуть игру")
        exit_button.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #c6b69a; padding: 6px; } "
            "QPushButton:hover { color: #ffe3ab; }"
        )
        exit_button.clicked.connect(window.close)
        layout.addWidget(exit_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.developer_button = QPushButton("⚙ Разработчик")
        self.developer_button.setToolTip("Локальный доступ к техническим настройкам")
        self.developer_button.clicked.connect(lambda: window.open_section("Разработчик"))
        self.add_menu_action(self.developer_button)
        layout.addStretch(3)
        footer = QLabel("ОДИН ГЕРОЙ. ТЫСЯЧА ПУТЕЙ. ВАША ИСТОРИЯ.")
        footer.setStyleSheet(
            "color: #9da9ab; font-size: 10px; letter-spacing: 2px; background: transparent;"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        window.home_title = self.title
        self.resizeEvent(None)

    def add_menu_action(self, button):
        button.setStyleSheet(BUTTON_STYLE)
        button.setMinimumHeight(36)
        self.actions.addWidget(button)

    def resizeEvent(self, event):
        self.title.setFont(QFont("Georgia", 32 if self.width() < 800 else 48))
        if hasattr(self.window, "notifications"):
            QTimer.singleShot(0, self.window.notifications.fit)
        if event:
            super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._scaled_size != self.size():
            self._scaled = self.art.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._scaled_size = self.size()
        painter.drawPixmap(
            (self.width() - self._scaled.width()) // 2,
            (self.height() - self._scaled.height()) // 2,
            self._scaled,
        )
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(3, 10, 20, 15))
        gradient.setColorAt(0.5, QColor(4, 12, 20, 45))
        gradient.setColorAt(1, QColor(2, 8, 15, 145))
        painter.fillRect(self.rect(), gradient)


def continue_adventure(window):
    session = window._session
    if session.progress.enabled or session.turns or session.generated_world:
        window.resume_session()
    else:
        window.open_section("Сохранения")
