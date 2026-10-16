"""The first window: a plain-text journal, an action field and an offline reply."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.narrative.offline import INTRODUCTION, respond


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Пограничье — первый прототип")
        self.resize(900, 640)
        self.setMinimumSize(560, 420)

        body = QWidget(self)
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("У ворот деревни")
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        mode = QLabel("Автономный режим · без нейросети и интернета")
        mode.setWordWrap(True)
        layout.addWidget(mode)

        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setAccessibleName("Журнал событий")
        self.journal.appendPlainText("Рассказчик: " + INTRODUCTION)
        layout.addWidget(self.journal, stretch=1)

        hint = QLabel("Попробуйте: осмотреться · поговорить · помочь. Подсказка: помощь.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        action_label = QLabel("Ваше действие:")
        layout.addWidget(action_label)
        input_row = QHBoxLayout()
        self.action_input = QLineEdit()
        self.action_input.setAccessibleName("Ваше действие")
        self.action_input.setPlaceholderText("Например: помочь собрать яблоки")
        self.action_input.setMaxLength(500)
        action_label.setBuddy(self.action_input)
        input_row.addWidget(self.action_input, stretch=1)

        self.send_button = QPushButton("Отправить")
        self.send_button.setEnabled(False)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        note = QLabel("Пробный эпизод. Журнал не сохраняется после закрытия окна.")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.action_input.textChanged.connect(
            lambda text: self.send_button.setEnabled(bool(text.strip()))
        )
        self.action_input.returnPressed.connect(self.submit_action)
        self.send_button.clicked.connect(self.submit_action)
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def submit_action(self) -> None:
        action = self.action_input.text().strip()
        if not action:
            return

        # appendPlainText keeps user-supplied HTML and links inert.
        self.journal.appendPlainText("\nВы: " + action)
        self.journal.appendPlainText("Рассказчик: " + respond(action))
        self.action_input.clear()
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self.journal.ensureCursorVisible()
