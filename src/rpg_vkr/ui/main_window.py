"""The first window: a plain-text journal, an action field and an offline reply."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.application import Session
from rpg_vkr.attribution import SRD_ATTRIBUTION
from rpg_vkr.domain.character import ABILITY_NAMES, ability_modifier
from rpg_vkr.domain.world import LOCATIONS, inventory_text, quest_text
from rpg_vkr.storage.slots import SaveError, SaveSlots, default_save_directory
from rpg_vkr.ui.character_dialog import CharacterDialog
from rpg_vkr.ui.episode_panels import EpisodePanels
from rpg_vkr.ui.workspace_panel import WorkspaceActions
from rpg_vkr.ui.workspace_tools import HistoryLineEdit


class MainWindow(EpisodePanels, WorkspaceActions, QMainWindow):
    def __init__(self, session: Session | None = None, saves: SaveSlots | None = None) -> None:
        super().__init__()
        self._session = Session() if session is None else session
        self._saves = SaveSlots(default_save_directory()) if saves is None else saves
        self._dirty = False
        self._current_slot: int | None = None
        self.setWindowTitle("Пограничье — первый прототип")
        self.resize(960, 780)
        self.setMinimumSize(640, 620)
        about = self.menuBar().addMenu("Справка").addAction("О программе и лицензии")
        about.triggered.connect(self._show_about)

        body = QWidget(self)
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("У ворот деревни")
        self.scene_title = title
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        mode = QLabel("Автономный режим · без нейросети и интернета")
        mode.setWordWrap(True)
        layout.addWidget(mode)

        self.resource_label = QLabel()
        self.resource_label.setWordWrap(True)
        self.resource_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.resource_label)

        self.tabs = QTabWidget()
        adventure = QWidget()
        play_layout = QVBoxLayout(adventure)
        play_layout.setContentsMargins(0, 8, 0, 0)
        self.tabs.addTab(adventure, "Приключение")
        profile = QWidget()
        profile_layout = QVBoxLayout(profile)
        self.tabs.addTab(profile, "Герой")
        layout.addWidget(self.tabs, stretch=1)

        self.character_group = QGroupBox()
        character_layout = QGridLayout(self.character_group)
        self.ability_labels: dict[str, QLabel] = {}
        for index, ability in enumerate(ABILITY_NAMES):
            label = QLabel()
            self.ability_labels[ability] = label
            character_layout.addWidget(label, index // 3, index % 3)
        profile_layout.addWidget(self.character_group)
        self.inventory_label = QLabel()
        self.inventory_label.setWordWrap(True)
        profile_layout.addWidget(self.inventory_label)
        self.quest_label = QLabel()
        self.quest_label.setWordWrap(True)
        profile_layout.addWidget(self.quest_label)
        controls = QHBoxLayout()
        self.new_character_button = QPushButton("Новый герой")
        self.edit_character_button = QPushButton("Редактировать героя")
        controls.addWidget(self.new_character_button)
        controls.addWidget(self.edit_character_button)
        profile_layout.addLayout(controls)
        note = QLabel(
            "Параметры эпизода — homebrew: 12 ОЗ, 10 золотых и 1 бинт в начале. "
            "Изменение характеристик не восполняет здоровье и не выдаёт ресурсы."
        )
        note.setWordWrap(True)
        profile_layout.addWidget(note)
        profile_layout.addStretch()
        self._refresh_character()

        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setAccessibleName("Журнал событий")
        self._render_journal()
        play_layout.addWidget(self.journal, stretch=1)

        quick = QGridLayout()
        self.quick_buttons: dict[str, QPushButton] = {}
        for index, (label, command) in enumerate(
            [
                ("Поручение", "взять поручение"),
                ("Дорога", "идти на дорогу"),
                ("Исследовать", "исследовать дорогу"),
                ("Рынок", "идти на рынок"),
                ("Доставить", "доставить корзину"),
                ("Торговец", "подойти к торговцу"),
                ("Использовать бинт", "использовать бинт"),
            ]
        ):
            button = QPushButton(label)
            button.setToolTip(command)
            button.clicked.connect(lambda checked=False, c=command: self._run_command(c))
            self.quick_buttons[command] = button
            quick.addWidget(button, index // 4, index % 4)
        play_layout.addLayout(quick)

        hint = QLabel(
            "Эпизод «Доставка на рынок». Можно вводить действия текстом. Подсказка: помощь."
        )
        hint.setWordWrap(True)
        play_layout.addWidget(hint)

        action_label = QLabel("Ваше действие:")
        play_layout.addWidget(action_label)
        input_row = QHBoxLayout()
        self.action_input = HistoryLineEdit()
        self.action_input.setAccessibleName("Ваше действие")
        self.action_input.setPlaceholderText("Например: проверить силу")
        self.action_input.setMaxLength(500)
        action_label.setBuddy(self.action_input)
        input_row.addWidget(self.action_input, stretch=1)

        self.send_button = QPushButton("Отправить")
        self.send_button.setEnabled(False)
        input_row.addWidget(self.send_button)
        play_layout.addLayout(input_row)

        slots_group = QGroupBox("Сохранения · 3 ячейки")
        slots_layout = QGridLayout(slots_group)
        self.slot_labels: dict[int, QLabel] = {}
        self.save_buttons: dict[int, QPushButton] = {}
        self.load_buttons: dict[int, QPushButton] = {}
        self.delete_buttons: dict[int, QPushButton] = {}
        for slot in (1, 2, 3):
            label = QLabel()
            label.setWordWrap(True)
            self.slot_labels[slot] = label
            slots_layout.addWidget(label, slot - 1, 0)
            for column, (title, handler, buttons) in enumerate(
                [
                    ("Сохранить", self.save_slot, self.save_buttons),
                    ("Загрузить", self.load_slot, self.load_buttons),
                    ("Удалить", self.delete_slot, self.delete_buttons),
                ],
                start=1,
            ):
                button = QPushButton(title)
                button.setAccessibleName(f"{title}: ячейка {slot}")
                button.clicked.connect(lambda checked=False, s=slot, h=handler: h(s))
                buttons[slot] = button
                slots_layout.addWidget(button, slot - 1, column)
        slots_layout.setColumnStretch(0, 1)

        note = QLabel(f"Сохранения: {self._saves.directory}")
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note.setWordWrap(True)

        self._build_workspace(play_layout, slots_group, note)
        self._build_episode_panels(layout)
        self.action_input.textChanged.connect(lambda text: self._refresh_workspace())
        self.action_input.textChanged.connect(
            lambda text: self.send_button.setEnabled(bool(text.strip()))
        )
        self.action_input.returnPressed.connect(self.submit_action)
        self.send_button.clicked.connect(self.submit_action)
        self.new_character_button.clicked.connect(self.new_character)
        self.edit_character_button.clicked.connect(self.edit_character)
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_slots()
        if session is None:
            self.open_section("Главное меню")

    def _refresh_character(self) -> None:
        self._refresh_workspace()
        self._refresh_episode_panels()
        character = self._session.character
        world = self._session.world
        self.character_group.setTitle(f"Персонаж: {character.name} · песочница")
        self.scene_title.setText(LOCATIONS[world.location])
        self.resource_label.setText(
            f"{character.name} · здоровье {world.hp}/{world.max_hp} · золото {world.gold} · "
            f"бинты {world.bandages} · {LOCATIONS[world.location]}"
        )
        self.inventory_label.setText("Инвентарь: " + inventory_text(world))
        self.quest_label.setText("Задание: " + quest_text(world))
        for ability, label in self.ability_labels.items():
            score = character.score(ability)
            label.setText(f"{ABILITY_NAMES[ability]}: {score} ({ability_modifier(score):+d})")

    def _run_command(self, command: str) -> None:
        draft = self.action_input.text()
        self.action_input.setText(command)
        self.submit_action()
        self.action_input.setText(draft)

    def new_character(self) -> None:
        from rpg_vkr.domain.character import Character

        dialog = CharacterDialog(Character(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if (self._dirty or self.action_input.text().strip()) and not self._confirm(
            "Начать новую сессию? Несохранённая текущая сессия будет потеряна. Ячейки останутся."
        ):
            return
        self._session = Session(character=dialog.character())
        self._dirty = True
        self._current_slot = None
        self.action_input.clear()
        self._refresh_character()
        self._render_journal()
        self._rebuild_history()
        self._refresh_slots()
        self.tabs.setCurrentIndex(0)
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def edit_character(self) -> None:
        dialog = CharacterDialog(self._session.character, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            changed = self._session.edit_character(dialog.character())
        except ValueError as error:
            QMessageBox.warning(self, "Профиль не изменён", str(error))
            return
        if changed:
            self._dirty = True
            self._refresh_character()
            self._render_journal()

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "О программе и лицензии",
            "Учебный офлайн-прототип DND-NCFU.\n\n"
            + SRD_ATTRIBUTION
            + "\n\nАдаптация: вычислительная реализация модификаторов и базовых проверок "
            "характеристик, русский интерфейс. Сюжет и учебный профиль — авторские. "
            "Это ограниченное подмножество правил, без владения навыками и боёв. "
            "Редактор — свободная песочница. Поручение, цены, здоровье и бинты — homebrew.",
        )

    def _render_journal(self) -> None:
        self.journal.setPlainText("Рассказчик: " + self._session.introduction)
        for turn in self._session.turns:
            self.journal.appendPlainText("\nВы: " + turn.action)
            self.journal.appendPlainText(f"{turn.speaker}: {turn.text}")
        self.journal.moveCursor(QTextCursor.MoveOperation.End)
        self.journal.ensureCursorVisible()

    def _refresh_slots(self) -> None:
        self._refresh_workspace()
        for slot in (1, 2, 3):
            info = self._saves.info(slot)
            active = " · активная" if slot == self._current_slot else ""
            self.slot_labels[slot].setText(f"Ячейка {slot}{active} — {info.description}")
            self.load_buttons[slot].setEnabled(info.occupied)
            self.delete_buttons[slot].setEnabled(info.occupied)

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Подтверждение",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def save_slot(self, slot: int) -> None:
        if self._saves.info(slot).occupied and not self._confirm(
            f"Перезаписать ячейку {slot}? Прежнее сохранение в ней будет заменено."
        ):
            return
        try:
            self._saves.save(slot, self._session)
        except SaveError as error:
            QMessageBox.warning(self, "Ошибка сохранения", str(error))
            return
        self._dirty = False
        self._current_slot = slot
        self._refresh_slots()
        self.statusBar().showMessage(f"Сессия сохранена в ячейке {slot}.", 6000)

    def load_slot(self, slot: int) -> None:
        try:
            session = self._saves.load(slot)
        except SaveError as error:
            QMessageBox.warning(self, "Ошибка загрузки", str(error))
            return
        if (self._dirty or self.action_input.text().strip()) and not self._confirm(
            f"Загрузить ячейку {slot}? Несохранённые изменения текущей сессии будут потеряны."
        ):
            return
        self._session = session
        self._dirty = False
        self._current_slot = slot
        self.action_input.clear()
        self._refresh_character()
        self._render_journal()
        self._rebuild_history()
        self._refresh_slots()
        self.resume_session()
        self.statusBar().showMessage(f"Загружена ячейка {slot}.", 6000)

    def delete_slot(self, slot: int) -> None:
        if not self._confirm(f"Удалить сохранение из ячейки {slot}? Это действие нельзя отменить."):
            return
        try:
            self._saves.delete(slot)
        except SaveError as error:
            QMessageBox.warning(self, "Ошибка удаления", str(error))
            return
        if self._current_slot == slot:
            self._current_slot = None
            self._dirty = True
        self._refresh_slots()
        self.statusBar().showMessage(
            f"Ячейка {slot} освобождена. Текущая сессия остаётся в окне.", 6000
        )

    def closeEvent(self, event) -> None:
        if (self._dirty or self.action_input.text().strip()) and not self._confirm(
            "Закрыть окно без сохранения? Нажмите «Нет», чтобы вернуться и сохранить сессию."
        ):
            event.ignore()
            return
        event.accept()

    def submit_action(self) -> None:
        action = self.action_input.text().strip()
        if not action:
            return

        try:
            turn = self._session.submit(action)
        except ValueError as error:
            QMessageBox.warning(self, "Действие не выполнено", str(error))
            return

        # appendPlainText keeps user-supplied HTML and links inert.
        self.journal.appendPlainText("\nВы: " + action)
        self.journal.appendPlainText(f"{turn.speaker}: {turn.text}")
        self._dirty = True
        self.action_input.remember(action)
        self._refresh_character()
        self.action_input.clear()
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self.journal.moveCursor(QTextCursor.MoveOperation.End)
        self.journal.ensureCursorVisible()
