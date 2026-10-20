"""Reading, navigation and file actions for the prototype window."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.ui.command_catalog import COMMAND_CATALOG
from rpg_vkr.ui.workspace_tools import (
    ReadingPreferences,
    atomic_text,
    load_preferences,
    save_preferences,
)


class WorkspaceActions:
    """UI-only actions. Game rules and the three-slot format stay in their modules."""

    def _build_workspace(self, play_layout, slots_group, slots_note) -> None:
        self._preferences_path = self._saves.directory.parent / "reading.json"
        self._system_palette = QPalette(self.palette())
        self._base_font = QFont(self.font())
        preferences, warning = load_preferences(self._preferences_path)

        inventory = QWidget()
        inventory_layout = QVBoxLayout(inventory)
        inventory_layout.addWidget(self.inventory_label)
        note = QLabel(
            "Бинт восстанавливает до 4 ОЗ. Корзина относится к поручению и сдаётся на рынке. "
            "В инвентаре только ваши вещи. Для торговли найдите торговца."
        )
        note.setWordWrap(True)
        inventory_layout.addWidget(note)
        for text, command in (("Использовать бинт", "использовать бинт"),):
            button = QPushButton(text)
            button.setProperty("game_action", True)
            button.setVisible(self._legacy_controls)
            button.clicked.connect(lambda checked=False, c=command: self._run_command(c))
            inventory_layout.addWidget(button)
        inventory_layout.addStretch()
        self.tabs.addTab(inventory, "Инвентарь")

        quest = QWidget()
        quest_layout = QVBoxLayout(quest)
        quest_layout.addWidget(self.quest_label)
        self.quest_progress = QProgressBar()
        self.quest_progress.setRange(0, 2)
        self.quest_progress.setFormat("Шаг %v из %m")
        quest_layout.addWidget(self.quest_progress)
        self.quest_action = QPushButton()
        self.quest_action.setProperty("game_action", True)
        self.quest_action.setVisible(self._legacy_controls)
        self.quest_action.clicked.connect(self._quest_command)
        quest_layout.addWidget(self.quest_action)
        quest_note = QLabel("Маршрут: ворота → рынок. Исследование дороги необязательно.")
        quest_note.setWordWrap(True)
        quest_layout.addWidget(quest_note)
        quest_layout.addStretch()
        self.tabs.addTab(quest, "Задание")

        reference = QWidget()
        reference_layout = QVBoxLayout(reference)
        self.command_search = QLineEdit()
        self.command_search.setPlaceholderText("Найти команду или описание")
        self.command_search.setAccessibleName("Поиск команд")
        reference_layout.addWidget(self.command_search)
        self.command_list = QListWidget()
        self.command_list.setWordWrap(True)
        for command, description in COMMAND_CATALOG:
            item = QListWidgetItem(f"{command} — {description}")
            item.setData(Qt.ItemDataRole.UserRole, command)
            self.command_list.addItem(item)
        reference_layout.addWidget(self.command_list, 1)
        self.insert_command_button = QPushButton("Подставить в поле действия")
        reference_layout.addWidget(self.insert_command_button)
        self.insert_command_button.setVisible(self._legacy_controls)
        tip = QLabel("Выберите команду. Она выполнится только после нажатия «Отправить».")
        tip.setWordWrap(True)
        reference_layout.addWidget(tip)
        self.tabs.addTab(reference, "Команды")
        self.command_search.textChanged.connect(self._filter_commands)
        self.command_list.itemDoubleClicked.connect(lambda item: self._insert_command())
        self.insert_command_button.clicked.connect(self._insert_command)
        self.command_list.setCurrentRow(0)
        self.command_list.currentItemChanged.connect(
            lambda current, previous: self.insert_command_button.setEnabled(current is not None)
        )

        settings = QWidget()
        settings_layout = QFormLayout(settings)
        self.settings_form = settings_layout
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 20)
        self.font_size.setValue(preferences.font_size)
        self.theme_choice = QComboBox()
        self.theme_choice.addItems(["Системная", "Светлая", "Тёмная"])
        self.theme_choice.setCurrentText(preferences.theme)
        settings_layout.addRow("Размер текста журнала:", self.font_size)
        settings_layout.addRow("Тема окна:", self.theme_choice)
        self.bold_text = QCheckBox("Жирный текст сообщений")
        self.bold_text.setChecked(preferences.bold_text)
        settings_layout.addRow(self.bold_text)
        reset = QPushButton("Вернуть стандартные настройки")
        reset.clicked.connect(self._reset_reading)
        settings_layout.addRow(reset)
        self.preferences_status = QLabel(warning or "Настройки чтения не меняют игровые ячейки.")
        self.preferences_status.setWordWrap(True)
        settings_layout.addRow(self.preferences_status)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings)
        self.tabs.addTab(settings_scroll, "Настройки")
        saves_tab = QWidget()
        saves_layout = QVBoxLayout(saves_tab)
        self.saves_layout = saves_layout
        saves_layout.addWidget(slots_group)
        saves_layout.addWidget(slots_note)
        saves_layout.addStretch()
        self.tabs.addTab(saves_tab, "Сохранения")

        self.bold_text.toggled.connect(self._change_reading)
        self.font_size.valueChanged.connect(self._change_reading)
        self.theme_choice.currentTextChanged.connect(self._change_reading)
        self._apply_reading(preferences)

        search = QHBoxLayout()
        self.journal_search = QLineEdit()
        self.journal_search.setPlaceholderText("Найти в журнале · Ctrl+F")
        self.journal_search.setAccessibleName("Поиск в журнале")
        find = QPushButton("Найти далее")
        find.clicked.connect(self.find_in_journal)
        self.journal_search.returnPressed.connect(self.find_in_journal)
        search.addWidget(self.journal_search, 1)
        search.addWidget(find)
        play_layout.insertLayout(0, search)

        self.session_status = QLabel()
        self.statusBar().addPermanentWidget(self.session_status)
        file_menu = self._make_file_menu()
        self.menuBar().insertMenu(self.menuBar().actions()[0], file_menu)
        # Keep actions owned by the menu so shortcuts stay active across all tabs.
        for label, shortcut, callback in (
            ("Новый герой…", "Ctrl+N", self.new_character),
            ("Сохранить сессию…", "Ctrl+S", self.quick_save),
            ("Загрузить сессию…", "Ctrl+O", self.choose_load),
            ("Найти в журнале", "Ctrl+F", self.focus_journal_search),
            ("Экспорт журнала…", "Ctrl+E", self.export_journal),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        self._rebuild_history()
        self._refresh_workspace()

    def _make_file_menu(self):
        from PySide6.QtWidgets import QMenu

        return QMenu("Сессия", self)

    def _refresh_workspace(self) -> None:
        if not hasattr(self, "session_status"):
            return
        step = {"available": 0, "active": 1, "completed": 2}[self._session.world.quest]
        self.quest_progress.setValue(step)
        self.quest_action.setText(
            ("Взять поручение у ворот", "Доставить корзину на рынке", "Завершено")[step]
        )
        world = self._session.world
        giver = self._session.combat.actor("villager")
        peace = self._session.combat.active is None and world.hp > 0
        self.quest_action.setEnabled(
            peace
            and (
                (
                    step == 0
                    and world.location == "gate"
                    and giver.hp > 0
                    and giver.disposition == "neutral"
                )
                or (step == 1 and world.location == "market")
            )
        )
        slot = f"Ячейка {self._current_slot}" if self._current_slot else "Без ячейки"
        state = "есть изменения" if self._dirty else "без изменений"
        draft = " · черновик не сохраняется" if self.action_input.text().strip() else ""
        self.session_status.setText(f"{slot} · {state}{draft}")
        self.setWindowTitle(f"DND-NCFU{' *' if self._dirty else ''} — Хроники забытых королевств")

    def _quest_command(self) -> None:
        self._run_command(
            "взять поручение" if self._session.world.quest == "available" else "доставить корзину"
        )

    def _filter_commands(self, query: str) -> None:
        first = None
        for index in range(self.command_list.count()):
            item = self.command_list.item(index)
            item.setHidden(query.casefold() not in item.text().casefold())
            if first is None and not item.isHidden():
                first = item
        self.command_list.setCurrentItem(first)
        self.insert_command_button.setEnabled(first is not None)

    def _insert_command(self) -> None:
        item = self.command_list.currentItem()
        if item is None or item.isHidden():
            return
        if self.action_input.text().strip() and not self._confirm(
            "Заменить черновик выбранной командой?"
        ):
            return
        self.action_input.setText(item.data(Qt.ItemDataRole.UserRole))
        self.tabs.setCurrentIndex(0)
        self.action_input.setFocus()

    def _rebuild_history(self) -> None:
        self.action_input.set_history(
            [turn.action for turn in self._session.turns if turn.speaker != "Система"]
        )

    def quick_save(self) -> None:
        if self._current_slot is not None:
            self.save_slot(self._current_slot)
            return
        slot = self._choose_slot("Сохранить сессию", occupied_only=False)
        if slot is not None:
            self.save_slot(slot)

    def choose_load(self) -> None:
        slot = self._choose_slot("Загрузить сессию", occupied_only=True)
        if slot is not None:
            self.load_slot(slot)

    def _choose_slot(self, title: str, *, occupied_only: bool) -> int | None:
        choices = {
            f"{slot} — {self._saves.info(slot).description}": slot
            for slot in (1, 2, 3)
            if not occupied_only or self._saves.info(slot).occupied
        }
        if not choices:
            self.statusBar().showMessage("Пока нет сохранённых сессий.", 6000)
            return None
        selected, accepted = QInputDialog.getItem(self, title, "Ячейка:", list(choices), 0, False)
        return choices.get(selected) if accepted else None

    def focus_journal_search(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.journal_search.setFocus()
        self.journal_search.selectAll()

    def find_in_journal(self) -> None:
        text = self.journal_search.text()
        if not text:
            return
        previous = self.journal.textCursor()
        if not self.journal.find(text):
            self.journal.moveCursor(QTextCursor.MoveOperation.Start)
            if not self.journal.find(text):
                self.journal.setTextCursor(previous)
                self.statusBar().showMessage("В журнале не найдено.", 5000)

    def export_journal(self) -> None:
        self._export_text(self.journal.toPlainText() + "\n", "Экспорт журнала", "journal.txt")

    def export_calculations(self) -> None:
        from rpg_vkr.narrative.presentation import present_turn

        entries = [
            f"Действие №{i + 1}: {turn.action}\n{present_turn(turn).details}"
            for i, turn in enumerate(self._session.turns)
            if turn.inspection or turn.roll or (turn.combat and turn.combat.outcome.rolls)
        ]
        text = "Разбор бросков сессии\n\n" + "\n\n".join(entries)
        self._export_text(text + "\n", "Экспорт расчётов", "rolls.txt")

    def _export_text(self, content: str, title: str, default_name: str) -> None:
        from pathlib import Path

        filename, _ = QFileDialog.getSaveFileName(self, title, default_name, "Текст (*.txt)")
        if not filename:
            return
        path = Path(filename)
        # Export must never overwrite a game slot or UI preferences.
        if path.resolve() == self._preferences_path.resolve() or path.resolve().is_relative_to(
            self._saves.directory.resolve()
        ):
            QMessageBox.warning(
                self, "Экспорт отменён", "Выберите файл вне папки игровых сохранений."
            )
            return
        try:
            atomic_text(path, content)
        except OSError as error:
            QMessageBox.warning(self, "Ошибка экспорта", str(error))
            return
        self.statusBar().showMessage(
            "Текст экспортирован. Для продолжения игры нужна ячейка.", 6000
        )

    def _apply_reading(self, preferences: ReadingPreferences) -> None:
        font = QFont(self._base_font)
        font.setPointSize(preferences.font_size)
        font.setBold(preferences.bold_text)
        self.journal.setFont(font)
        if hasattr(self, "roll_history"):
            self.roll_history.setFont(font)
        if hasattr(self, "combat_result"):
            self.combat_result.setFont(font)
        if hasattr(self, "world_memory_view"):
            self.world_memory_view.setFont(font)
            self.narrator_context.setFont(font)
        if hasattr(self, "roll_breakdown"):
            self.roll_breakdown.setFont(font)
            self.action_result.setFont(font)
        palette = QPalette(self._system_palette)
        if preferences.theme != "Системная":
            dark = preferences.theme == "Тёмная"
            colors = {
                QPalette.ColorRole.Window: "#242424" if dark else "#f4f4f4",
                QPalette.ColorRole.Base: "#181818" if dark else "#ffffff",
                QPalette.ColorRole.AlternateBase: "#303030" if dark else "#eeeeee",
                QPalette.ColorRole.Button: "#353535" if dark else "#e4e4e4",
                QPalette.ColorRole.Text: "#eeeeee" if dark else "#161616",
                QPalette.ColorRole.WindowText: "#eeeeee" if dark else "#161616",
                QPalette.ColorRole.ButtonText: "#eeeeee" if dark else "#161616",
                QPalette.ColorRole.Highlight: "#3569ac",
                QPalette.ColorRole.HighlightedText: "#ffffff",
                QPalette.ColorRole.ToolTipBase: "#242424" if dark else "#ffffff",
                QPalette.ColorRole.ToolTipText: "#eeeeee" if dark else "#161616",
                QPalette.ColorRole.PlaceholderText: "#aaaaaa" if dark else "#626262",
            }
            for role, color in colors.items():
                palette.setColor(role, QColor(color))
            for role in (
                QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText,
                QPalette.ColorRole.WindowText,
            ):
                palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#858585"))
        if self._legacy_controls:
            self.setPalette(palette)
        else:
            from rpg_vkr.ui.theme import apply_theme

            apply_theme(self, preferences.theme)
            palette = self.palette()
        self.journal.set_role_theme(palette.color(QPalette.ColorRole.Base).lightness() < 128)
        if hasattr(self, "combat_targets"):
            self._refresh_episode_panels()

    def _change_reading(self) -> None:
        preferences = ReadingPreferences(
            self.font_size.value(), self.theme_choice.currentText(), self.bold_text.isChecked()
        )
        self._apply_reading(preferences)
        try:
            save_preferences(self._preferences_path, preferences)
        except OSError:
            self.preferences_status.setText(
                "Настройки применены, но не сохранены: нет доступа к файлу."
            )
        else:
            self.preferences_status.setText("Настройки чтения сохранены отдельно от сессии.")

    def _reset_reading(self) -> None:
        self.font_size.blockSignals(True)
        self.theme_choice.blockSignals(True)
        self.font_size.setValue(13)
        self.bold_text.blockSignals(True)
        self.bold_text.setChecked(True)
        self.bold_text.blockSignals(False)
        self.theme_choice.setCurrentText("Системная")
        self.font_size.blockSignals(False)
        self.theme_choice.blockSignals(False)
        self._change_reading()
