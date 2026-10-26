"""Campaign window: free input, contextual interactions and durable memory."""

import sqlite3

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
    QScrollArea,
    QStackedWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.application import Session
from rpg_vkr.attribution import SRD_ATTRIBUTION
from rpg_vkr.domain.character import ABILITY_NAMES, ability_modifier
from rpg_vkr.domain.progression import describe_progress
from rpg_vkr.domain.world import inventory_text, quest_text
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveError, SaveSlots, default_save_directory
from rpg_vkr.ui.character_dialog import CharacterDialog
from rpg_vkr.ui.creation_dialog import CreationDialog
from rpg_vkr.ui.episode_panels import EpisodePanels
from rpg_vkr.ui.narrator_panel import after_action, request_chat, request_local_actions
from rpg_vkr.ui.resolution_panel import install_resolution_panel
from rpg_vkr.ui.role_journal import RoleJournal
from rpg_vkr.ui.workspace_panel import WorkspaceActions
from rpg_vkr.ui.workspace_tools import HistoryLineEdit


class MainWindow(EpisodePanels, WorkspaceActions, QMainWindow):
    def __init__(
        self,
        session: Session | None = None,
        saves: SaveSlots | None = None,
        *,
        legacy_controls=False,
    ) -> None:
        super().__init__()
        self._legacy_controls = legacy_controls
        self._session = Session() if session is None else session
        self._saves = SaveSlots(default_save_directory()) if saves is None else saves
        self._archive_error = ""
        self._campaign_repository = None
        self._generating_session = None
        try:
            self._campaign_repository = CampaignRepository(
                self._saves.directory.parent / "campaigns.sqlite3"
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            self._archive_error = "Рабочая память недоступна: " + str(error)
        self._dirty = False
        self._current_slot: int | None = None
        from rpg_vkr.build_info import DISPLAY_NAME

        self.setWindowTitle(DISPLAY_NAME)
        self.resize(1180, 800)
        self.setMinimumSize(640, 620)
        about = self.menuBar().addMenu("Справка").addAction("О программе и лицензии")
        about.triggered.connect(self._show_about)

        body = QWidget(self)
        self.game_body = body
        self.screen_stack = QStackedWidget()
        self.screen_stack.addWidget(body)
        self.setCentralWidget(self.screen_stack)
        columns = QHBoxLayout(body)
        self._columns_layout = columns
        columns.setContentsMargins(0, 0, 12, 0)
        content = QWidget()
        columns.addWidget(content, stretch=1)
        layout = QVBoxLayout(content)
        self._content_layout = layout
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
        self.mode_label = mode
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
        profile_scroll = QScrollArea()
        profile_scroll.setWidgetResizable(True)
        profile_scroll.setWidget(profile)
        self.tabs.addTab(profile_scroll, "Герой")
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
        self.hero_description_view = QPlainTextEdit()
        self.hero_description_view.setReadOnly(True)
        self.hero_description_view.setMaximumHeight(150)
        self.hero_description_view.setAccessibleName("Сохранённое описание и прошлое героя")
        profile_layout.addWidget(self.hero_description_view)
        controls = QHBoxLayout()
        self.new_character_button = QPushButton("Новый герой")
        self.edit_character_button = QPushButton("Редактировать героя")
        controls.addWidget(self.new_character_button)
        controls.addWidget(self.edit_character_button)
        profile_layout.addLayout(controls)
        note = QLabel(
            "Создание и развитие — авторские правила, не полные классы SRD. "
            "Старый свободный редактор доступен только учебной песочнице."
        )
        note.setWordWrap(True)
        profile_layout.addWidget(note)
        profile_layout.addStretch()
        self.progress_label = QLabel()
        self.progress_label.setWordWrap(True)
        profile_layout.insertWidget(1, self.progress_label)
        from rpg_vkr.ui.skill_panel import install as install_skills

        install_skills(self, profile_layout)
        self._refresh_character()

        self.journal = RoleJournal()
        self.journal.setReadOnly(True)
        self.journal.setAccessibleName("Журнал событий")
        self._render_journal()
        legend = QLabel("Цвета Мастера, героя и NPC настраиваются в настройках игрового журнала")
        legend.setWordWrap(True)
        play_layout.addWidget(legend)
        play_layout.addWidget(self.journal, stretch=1)

        if not self._legacy_controls:
            from rpg_vkr.ui.adventure_panel import retry_world
            from rpg_vkr.ui.world_creation_screen import WorldCreationScreen

            self.world_creation_screen = WorldCreationScreen()
            self.screen_stack.addWidget(self.world_creation_screen)
            self.world_retry_button = self.world_creation_screen.create_button
            self.world_start_status = self.world_creation_screen.detail
            self.world_creation_screen.start_requested.connect(lambda: retry_world(self))
            self.world_creation_screen.cancel_requested.connect(self.cancel_world_creation)
            self.world_creation_screen.menu_requested.connect(
                lambda: self.open_section("Главное меню")
            )

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
            button.setProperty("game_action", True)
            button.setToolTip(command)
            button.clicked.connect(lambda checked=False, c=command: self._run_command(c))
            if command == "использовать бинт":
                button.setToolTip("В схватке лечение тратит действие; противник отвечает.")
            self.quick_buttons[command] = button
            quick.addWidget(button, index // 4, index % 4)
        self.quick_controls = QWidget()
        self.quick_controls.setLayout(quick)
        play_layout.addWidget(self.quick_controls)
        self.quick_controls.setVisible(self._legacy_controls)

        hint = QLabel(
            "Опишите действие своими словами. Мастер отвечает в журнале; расчёты показаны справа."
        )
        hint.setWordWrap(True)
        play_layout.addWidget(hint)

        action_label = QLabel("Ваше действие:")
        play_layout.addWidget(action_label)
        input_row = QHBoxLayout()
        self.action_input = HistoryLineEdit()
        self.action_input.setAccessibleName("Ваше действие")
        self.action_input.setPlaceholderText("Опишите действие героя или обратитесь к мастеру")
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
        install_resolution_panel(self, columns)
        from rpg_vkr.ui.flash_settings import install_flash_settings

        install_flash_settings(self)
        if not self._legacy_controls:
            from rpg_vkr.ui.visuals_panel import install_visuals

            try:
                install_visuals(self)
            except (ValueError, OSError, sqlite3.Error):
                if hasattr(self, "artist_page"):
                    self.artist_page.addWidget(
                        QLabel("Хранилище изображений недоступно. Мастер работает отдельно.")
                    )
                self.settings_form.addRow(
                    QLabel(
                        "Хранилище изображений недоступно. "
                        "Игра и текстовый мастер работают отдельно."
                    )
                )
        if not self._legacy_controls:
            from rpg_vkr.ui.developer_panel import install_developer

            install_developer(self)
            from rpg_vkr.ui.photo_album import PhotoAlbum

            self.photo_album = PhotoAlbum(self)
            self.tabs.addTab(self.photo_album, "Фотоальбом")
            if hasattr(self, "visuals"):
                self.visuals.changed.connect(self.photo_album.refresh)
            from rpg_vkr.ui.section_tabs import install_section_tabs

            install_section_tabs(self)
            from rpg_vkr.ui.tester_connection import install_tester_connection

            install_tester_connection(self)
        self.action_input.textChanged.connect(lambda text: self._refresh_workspace())
        self.action_input.textChanged.connect(
            lambda text: self.send_button.setEnabled(
                bool(text.strip()) and self._generating_session is not self._session
            )
        )
        self.action_input.returnPressed.connect(self.submit_action)
        self.send_button.clicked.connect(self.submit_action)
        self.new_character_button.clicked.connect(self.new_character)
        self.edit_character_button.clicked.connect(self.edit_character)
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_slots()
        self._refresh_character()
        if not self._legacy_controls:
            self.open_section("Главное меню")
        elif session is None:
            self.open_section("Главное меню")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "quick_controls"):
            # The text field remains the main input on compact screens.
            self.quick_controls.setVisible(self._legacy_controls and self.width() >= 1000)
        if hasattr(self, "resolution_panel") and not self._legacy_controls:
            from rpg_vkr.ui.theme import sync_chrome

            sync_chrome(self, self.tabs.currentIndex())

    def show_compact_rolls(self):
        """Reuse the very same calculations in a readable dialog on a small screen."""
        from rpg_vkr.ui.theme import sync_chrome

        dialog = QDialog(self)
        dialog.setWindowTitle("Кубики и результат")
        dialog.resize(520, 540)
        layout = QVBoxLayout(dialog)
        self._roll_dialog_open = True
        self.resolution_panel.setMaximumWidth(16777215)
        layout.addWidget(self.resolution_panel)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        self.resolution_panel.show()
        try:
            dialog.exec()
        finally:
            self._columns_layout.addWidget(self.resolution_panel)
            self.resolution_panel.setMaximumWidth(330)
            self._roll_dialog_open = False
            sync_chrome(self, self.tabs.currentIndex())

    def _refresh_character(self) -> None:
        from rpg_vkr.ui.skill_panel import refresh as refresh_skills

        refresh_skills(self)
        from rpg_vkr.ui.gameplay_panel import refresh as refresh_gameplay

        refresh_gameplay(self)
        self._refresh_workspace()
        self._refresh_episode_panels()
        character = self._session.effective_character
        world = self._session.world
        if (
            self.hero_description_view.toPlainText()
            != self._session.campaign.raw_player_description
        ):
            self.hero_description_view.setPlainText(self._session.campaign.raw_player_description)
        self.hero_description_view.setVisible(bool(self._session.campaign.raw_player_description))
        self.character_group.setTitle(
            f"Персонаж: {character.name} · "
            + ("герой" if self._session.progress.enabled else "песочница")
        )
        self.progress_label.setText(describe_progress(self._session.progress))
        if self._session.gameplay:
            progress = self._session.d20_progress
            self.progress_label.setText(
                f"Приключение D20 · уровень {progress.level} · XP {progress.xp}"
            )
        self.edit_character_button.setEnabled(
            not self._session.progress.enabled
            and self._session.combat.active is None
            and world.hp > 0
        )
        self.edit_character_button.setToolTip(
            "Созданный герой развивается действиями; "
            "свободный редактор — только для старой песочницы."
        )
        if hasattr(self, "journal"):
            self.journal.hero_name = character.name
        draft = not self._legacy_controls and not self._session.generated_world
        self.scene_title.setText("Мир ещё не создан" if draft else self._session.current_place_name)
        self.resource_label.setText(
            f"{character.name} · здоровье {world.hp}/{world.max_hp} · золото {world.gold} · "
            f"бинты {world.bandages} · {self._session.current_place_name}"
        )
        if self._session.gameplay:
            self.resource_label.setText(
                f"{character.name} · HP {world.hp}/{world.max_hp} · "
                f"{world.gold * 100 + self._session.gameplay['copper']} медных · "
                f"бинты {world.bandages} · {self._session.current_place_name}"
            )
        if draft:
            from rpg_vkr.ui.adventure_panel import world_start_message

            self.resource_label.setText(world_start_message(self))
            if hasattr(self, "map_location"):
                self.map_location.setText("Мир ещё не создан.")
        extras = "; ".join(name + " ×1" for name, _ in self._session.extra_items)
        self.inventory_label.setText(
            "Инвентарь: " + inventory_text(world) + ("; " + extras if extras else "")
        )
        self.quest_label.setText("Задание: " + quest_text(world))
        for ability, label in self.ability_labels.items():
            score = character.score(ability)
            label.setText(f"{ABILITY_NAMES[ability]}: {score} ({ability_modifier(score):+d})")
        if self._session.generated_world and hasattr(self, "home_summary"):
            hooks = "\n".join(self._session.chronicle.seed.hooks)
            self.quest_label.setText("Зацепки: " + hooks)
            self.home_summary.setText(
                self._session.chronicle.seed.title + " · " + self._session.current_place_name
            )
            if self._legacy_controls:
                self.home_title.setText(self._session.chronicle.seed.title)
            places = [
                p
                for p in self._session.interaction_state().places
                if p.id in self._session.visited_places
            ]
            self.known_places.setRowCount(len(places))
            for row, place in enumerate(places):
                self.known_places.setItem(row, 0, QTableWidgetItem(place.name))
                self.known_places.setItem(row, 1, QTableWidgetItem(place.description))
            self.map_location.setText("Вы здесь: " + self._session.current_place_name)
            self.exploration_status.setText(
                "Известные места: "
                + "; ".join(
                    p.name
                    for p in self._session.interaction_state().places
                    if p.id in self._session.visited_places
                )
            )
        if hasattr(self, "chronicles_panel"):
            from rpg_vkr.ui.chronicles_panel import card_html

            places = [e for e in self.chronicles_panel.entries if e.category == "places"]
            self.known_places.setRowCount(len(places))
            for row, place in enumerate(places):
                item = QTableWidgetItem(place.title)
                item.setData(Qt.ItemDataRole.UserRole, place.key)
                item.setToolTip(card_html(place, True))
                self.known_places.setItem(row, 0, item)
                self.known_places.setItem(row, 1, QTableWidgetItem(place.description))
            self.map_location.setText(
                "Мир ещё не создан." if draft else "Вы здесь: " + self._session.current_place_name
            )
        if hasattr(self, "world_start_status"):
            from rpg_vkr.ui.adventure_panel import refresh_world_start

            refresh_world_start(self)
        if hasattr(self, "photo_album"):
            self.photo_album.refresh()
        self._persist_campaign()
        if hasattr(self, "diary_list"):
            from rpg_vkr.ui.adventure_panel import refresh_diary
            from rpg_vkr.ui.context_actions import refresh_context

            refresh_diary(self)
            refresh_context(self)

    def _persist_campaign(self):
        if not self._campaign_repository:
            return
        try:
            if self._session.progress.enabled or self._session.turns or self._session.chronicle:
                self._campaign_repository.sync(self._session)
            self._session._memory_provider = self._recall_campaign
            if hasattr(self, "campaign_choice"):
                selected = self.campaign_choice.currentData()
                self.campaign_choice.clear()
                for id, hero, title, _ in self._campaign_repository.list_campaigns():
                    self.campaign_choice.addItem(hero + " · " + title, id)
                self.campaign_choice.setCurrentIndex(
                    max(0, self.campaign_choice.findData(selected))
                )
            self._archive_error = ""
        except (OSError, ValueError, sqlite3.Error) as error:
            self._archive_error = "Память не записана: " + str(error)
            self.statusBar().showMessage(self._archive_error)

    def _recall_campaign(self, text, private=False):
        try:
            return self._campaign_repository.recall(self._session, text, private=private)
        except (OSError, ValueError, sqlite3.Error) as error:
            self._archive_error = "Память недоступна: " + str(error)
            return {}

    def _run_command(self, command: str) -> None:
        draft = self.action_input.text()
        self.action_input.setText(command)
        self.submit_action(use_ai=False, origin="quick")
        self.action_input.setText(draft)

    def new_character(self) -> None:
        from rpg_vkr.ui.cloud_gate import require_cloud

        if not require_cloud(self):
            return
        dialog = CreationDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if (
            self._dirty or self.action_input.text().strip() or getattr(self, "_diary_draft", False)
        ) and not self._confirm(
            "Начать новую сессию? Несохранённая текущая сессия будет потеряна. Ячейки останутся."
        ):
            return
        self._generating_session = None
        self.ollama.cancel()
        self._session = dialog.create_session()
        self.action_input.setEnabled(True)
        self._dirty = True
        self._current_slot = None
        self.action_input.clear()
        self._refresh_character()
        self._render_journal()
        self._rebuild_history()
        self._refresh_slots()
        self.tabs.setCurrentIndex(0)
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)
        if not self._legacy_controls:
            self.show_world_creation()
        elif dialog.generate_world.isChecked():
            from rpg_vkr.ui.adventure_panel import begin_world

            begin_world(self)

    def show_world_creation(self):
        if not hasattr(self, "world_creation_screen"):
            return
        self.screen_stack.setCurrentWidget(self.world_creation_screen)
        self.menuBar().hide()
        self.statusBar().hide()
        if self.world_creation_screen.state in {"ready", "error"}:
            self.world_creation_screen.create_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_game_body(self):
        if not self._legacy_controls and not self._session.generated_world:
            from rpg_vkr.ui.navigation_policy import GAME

            if self.tabs.tabText(self.tabs.currentIndex()) in GAME:
                menu = next(
                    i for i in range(self.tabs.count()) if self.tabs.tabText(i) == "Главное меню"
                )
                self.tabs.setCurrentIndex(menu)
        self.screen_stack.setCurrentWidget(self.game_body)
        if hasattr(self, "resolution_panel") and not self._legacy_controls:
            from rpg_vkr.ui.theme import sync_chrome

            sync_chrome(self, self.tabs.currentIndex())

    def cancel_world_creation(self):
        from rpg_vkr.ui.narrator_panel import cancel_narration

        if self._generating_session is self._session:
            cancel_narration(self)

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
            "DND-NCFU · Хроники забытых королевств\nВерсия 1R · Автор проекта: sayferst\n"
            "Учебная RPG для ВКР по моделированию конфликтных ситуаций.\n"
            "Python 3.12 · PySide6 · SQLite. Облачный ИИ-мастер, локальные сохранения.\n\n"
            + SRD_ATTRIBUTION
            + "\n\nАдаптация: вычислительная реализация модификаторов и базовых проверок "
            "характеристик, русский интерфейс. Сюжет и учебный профиль — авторские. "
            "Подмножество SRD ограничено проверками, без владения навыками. "
            "Старый редактор — песочница. Профили, бюджет, развитие, "
            "уровни, схватки, цены и бинты — homebrew.",
        )

    def _render_journal(self) -> None:
        self.journal.hero_name = self._session.character.name
        self.journal.clear()
        if getattr(self, "_generating_session", None) is self._session:
            self.journal.append_message(
                "narrator",
                "Мастер",
                "Создаётся ваш мир: место появления, обитатели и сюжетные зацепки…",
            )
            return
        draft = not self._legacy_controls and not self._session.generated_world
        if draft:
            from rpg_vkr.ui.adventure_panel import world_start_message

            self.journal.append_message("narrator", "Мастер", world_start_message(self))
            if not self._session.turns:
                return
        notes = {note.turn_index: note for note in self._session.narrations}
        if 0 in notes:
            self._append_narration(notes[0])
        elif not draft:
            self.journal.append_message("narrator", "Мастер", self._session.introduction)
        for index, turn in enumerate(self._session.turns, 1):
            if turn.combat or turn.inspection:
                # The checked result remains visible while the writer thinks or fails.
                self.journal.append_turn(turn)
                if index in notes:
                    self._append_narration(notes[index])
                continue
            if index in notes:
                self.journal.append_player(turn)
                self._append_narration(notes[index])
            elif (
                turn.intent
                and getattr(self, "_narrating_session", None) is self._session
                and self._narrating_index == index
                and self._chat_text is None
            ):
                self.journal.append_player(turn)
            else:
                self.journal.append_turn(turn)
        self.journal.moveCursor(QTextCursor.MoveOperation.End)
        self.journal.ensureCursorVisible()
        self._persist_campaign()

    def _append_narration(self, note) -> None:
        actor_id = None
        if note.turn_index:
            turn = self._session.turns[note.turn_index - 1]
            if turn.dialogue:
                actor_id = turn.dialogue.target
            elif turn.actor_id in {"guard", "villager", "merchant"}:
                actor_id = turn.actor_id  # Preserve trusted attribution in older saves too.
            elif turn.catalog and hasattr(turn.catalog, "target_id"):
                actor_id = turn.catalog.target_id
        if not actor_id and self._session.generated_world:
            import re

            named = [
                a.id
                for a in self._session.interaction_state().actor_refs
                if re.search(r"\b" + re.escape(a.name) + r"\b", note.text, re.I)
            ]
            if len(named) == 1:
                actor_id = named[0]
        if note.prompt_version in {
            "narrator-prose-11",
            "narrator-prose-12",
            "narrator-prose-13",
            "narrator-prose-14",
        }:
            self.journal.append_master_story(note.text, actor_id=actor_id)
        elif note.segments:
            self.journal.append_segments(note.segments)
        else:
            self.journal.append_story(note.text, actor_id=actor_id)

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
        if self._generating_session is self._session:
            self.statusBar().showMessage("Дождитесь создания мира или отмените ожидание.")
            return
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
        if (
            self._dirty or self.action_input.text().strip() or getattr(self, "_diary_draft", False)
        ) and not self._confirm(
            f"Загрузить ячейку {slot}? Несохранённые изменения текущей сессии будут потеряны."
        ):
            return
        self._generating_session = None
        self.ollama.cancel()
        self.action_input.setEnabled(True)
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
        if (
            self._dirty or self.action_input.text().strip() or getattr(self, "_diary_draft", False)
        ) and not self._confirm(
            "Закрыть окно? Рабочая кампания уже записана в базу, если нет сообщения об ошибке. "
            "Ячейка сохранения не обновится; неотправленный ввод и "
            "несохранённая заметка будут потеряны. "
            "Нажмите «Нет», чтобы вернуться."
        ):
            event.ignore()
            return
        if hasattr(self, "visuals"):
            self.visuals.close()
        if hasattr(self, "motion"):
            self.motion.stop()
            for glow in self.button_glows:
                glow.animation.stop()
                glow.button.removeEventFilter(glow)
            self.notifications.timer.stop()
            self.notifications.fade.stop()
        if hasattr(self, "developer_console") and hasattr(self.developer_console, "gateway_client"):
            self.developer_console.gateway_client.cancel()
        if hasattr(self, "developer_console"):
            self.developer_console.learning.shutdown()
        self._closing = True
        self.routerai_catalog.cancel()
        self.routerai_key_client.cancel()
        self.ollama.cancel()
        event.accept()

    def submit_action(self, *, use_ai=True, origin="typed") -> None:
        action = self.action_input.text().strip()
        if not action:
            return
        if not self._legacy_controls:
            from rpg_vkr.ui.visual_commands import handle_visual_text

            if handle_visual_text(self, action):
                return
        from rpg_vkr.ui.cloud_gate import require_cloud, require_world

        if not require_cloud(self) or not require_world(self):
            return
        if use_ai and getattr(self, "_flash_pending", False):
            self.narrator_status.setText(
                "Проверяется подключение мастера. Реплика сохранена в поле ввода; "
                "отправьте после проверки."
            )
            return
        if self._session.gameplay:
            from rpg_vkr.domain.gameplay_commands import parse

            if parse(action):
                use_ai = False
                origin = "quick"
        if origin == "typed" and request_local_actions(self, action):
            return
        if use_ai and request_chat(self, action):
            return

        try:
            turn = self._session.submit(action, origin=origin)
        except ValueError as error:
            QMessageBox.warning(self, "Действие не выполнено", str(error))
            return

        # appendPlainText keeps user-supplied HTML and links inert.
        self.journal.append_turn(turn)
        self._dirty = True
        self.action_input.remember(action)
        self._refresh_character()
        self.action_input.clear()
        self.action_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self.journal.moveCursor(QTextCursor.MoveOperation.End)
        self.journal.ensureCursorVisible()
        after_action(self, turn)
