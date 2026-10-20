"""Complete screens for the existing episode; all mutations go through Session."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.application import CHECK_COMMANDS
from rpg_vkr.domain.character import ABILITY_NAMES
from rpg_vkr.domain.combat import disposition_label
from rpg_vkr.domain.progression import describe_award
from rpg_vkr.domain.world import LOCATIONS
from rpg_vkr.ui.catalog_panel import install_catalog_panel, refresh_catalog_panel
from rpg_vkr.ui.combat_panel import install_combat_panel, refresh_combat_panel
from rpg_vkr.ui.narrator_panel import install_narrator_panels, refresh_narrator_panels
from rpg_vkr.ui.resolution_panel import refresh_resolution_panel

TRAVEL_COMMANDS = {"gate": "идти к воротам", "road": "идти на дорогу", "market": "идти на рынок"}
RESIDENTS = (
    ("Стражник", "gate", "Встречает путников у ворот. Можно поговорить."),
    ("Жительница", "gate", "Предлагает доставить корзину на рынок. Можно помочь."),
    ("Торговец", "market", "Стоит у прилавка. Подойдите, чтобы узнать о товаре."),
)


def plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().hide()
    return table


class EpisodePanels:
    """Views of the small world, never a second implementation of the rules."""

    def _episode_page(self, name: str):
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, name)
        return layout

    def _panel_button(self, layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        names = getattr(getattr(callback, "__code__", None), "co_names", ())
        action = (
            bool(
                set(names)
                & {"_run_command", "attack_selected", "send_selected", "provoke_selected"}
            )
            or getattr(callback, "__name__", "") == "_talk_to_resident"
        )
        if action:
            button.setProperty("game_action", True)
            button.setVisible(self._legacy_controls)
        layout.addWidget(button)
        return button

    def _build_episode_panels(self, root_layout) -> None:
        if self._legacy_controls:
            menu = self._episode_page("Главное меню")
            self.home_title = plain_label("DND-NCFU · Приключение")
            menu.addWidget(self.home_title)
            self.home_summary = plain_label()
            menu.addWidget(self.home_summary)
            self._panel_button(menu, "Новый герой…", self.new_character)
            self.resume_button = self._panel_button(
                menu, "Вернуться к текущей сессии", self.resume_session
            )
            self._panel_button(menu, "Загрузить сохранение…", self.choose_load)
            self._panel_button(menu, "Сохранить текущую сессию…", self.quick_save)
            self._panel_button(menu, "Настройки", lambda: self.open_section("Настройки"))
            self._panel_button(menu, "Как играть", lambda: self.open_section("Как играть"))
            self._panel_button(menu, "Выйти", self.close)
            menu.addWidget(
                plain_label(
                    "Рабочая кампания сохраняется в SQLite. Три ячейки — отдельные "
                    "контрольные точки, они обновляются вручную."
                )
            )
            menu.addStretch()

        else:
            from rpg_vkr.ui.main_menu import MainMenu

            self.tabs.addTab(MainMenu(self), "Главное меню")

        map_layout = self._episode_page("Карта")
        map_layout.addWidget(
            plain_label(
                "Известные места и видимые направления. Переходы задаются через "
                "чат; неизвестный район раскрывается по мере исследования."
            )
        )
        self.ask_market = self._panel_button(
            map_layout,
            "Узнать дорогу у стражника",
            lambda: self._run_command("узнать дорогу на рынок"),
        )
        self.map_location = plain_label()
        map_layout.addWidget(self.map_location)
        self.known_places = readonly_table(["Место", "Что известно"])
        if not self._legacy_controls:

            def open_place(row, column):
                key = self.known_places.item(row, 0).data(Qt.ItemDataRole.UserRole)
                if key:
                    self.open_section("Хроники мира")
                    self.chronicles_panel.open_entry(key)

            self.known_places.cellDoubleClicked.connect(open_place)
            self.known_places.setToolTip("Двойной щелчок или Enter: карточка места в Хрониках")
        map_layout.addWidget(self.known_places, 1)
        self.travel_buttons = {}
        for location, name in LOCATIONS.items():
            self.travel_buttons[location] = self._panel_button(
                map_layout,
                name,
                lambda checked=False, c=TRAVEL_COMMANDS[location]: self._run_command(c),
            )
        self.exploration_status = plain_label()
        map_layout.addWidget(self.exploration_status)
        self.map_explore = self._panel_button(
            map_layout, "Исследовать дорогу", lambda: self._run_command("исследовать дорогу")
        )
        map_layout.addStretch()

        people = self._episode_page("Жители")
        people.addWidget(
            plain_label(
                "Жители этого эпизода. Диалоги короткие, авторские. "
                "Отношения и память NPC ещё не реализованы."
            )
        )
        self.resident_list = QListWidget()
        self.resident_list.setAccessibleName("Жители эпизода")
        for name, _location, _ in RESIDENTS:
            self.resident_list.addItem(name)
        people.addWidget(self.resident_list)
        self.resident_description = plain_label()
        people.addWidget(self.resident_description)
        self.resident_talk = self._panel_button(people, "Поговорить здесь", self._talk_to_resident)
        self.resident_help = self._panel_button(
            people, "Помочь жительнице", lambda: self._run_command("помочь")
        )
        self.resident_quest = self._panel_button(
            people, "Взять поручение", lambda: self._run_command("взять поручение")
        )
        self.resident_reply = QPlainTextEdit()
        self.resident_reply.setReadOnly(True)
        self.resident_reply.setAccessibleName("Последний разговор")
        people.addWidget(self.resident_reply)
        self.resident_list.currentRowChanged.connect(self._refresh_resident)
        self.resident_list.setCurrentRow(0)

        shop = self._episode_page("Лавка")
        self.approach_merchant = self._panel_button(
            shop,
            "Подойти к торговцу и спросить о товаре",
            lambda: self._run_command("подойти к торговцу"),
        )
        self.shop_summary = plain_label()
        shop.addWidget(self.shop_summary)
        shop.addWidget(plain_label("Ассортимент и цены становятся известны при разговоре."))
        self.shop_buy = self._panel_button(
            shop, "Купить один бинт · 3 золотых", lambda: self._run_command("купить бинт")
        )
        self.shop_sell = self._panel_button(
            shop, "Продать один бинт · 1 золотой", lambda: self._run_command("продать бинт")
        )
        self.shop_reply = QPlainTextEdit()
        self.shop_reply.setReadOnly(True)
        self.shop_reply.setAccessibleName("Ответ торговца")
        shop.addWidget(self.shop_reply)
        self.shop_reason = plain_label()
        shop.addWidget(self.shop_reason)
        self.shop_travel = self._panel_button(
            shop, "Перейти на рынок", lambda: self._run_command("идти на рынок")
        )
        shop.addStretch()

        dice = self._episode_page("Кубики")
        dice.addWidget(
            plain_label(
                "Кубик с 20 гранями и проверки характеристик против сложности 10. "
                "Проверки в этой панели не меняют ресурсы мира."
            )
        )
        self._panel_button(dice, "Бросить кубик", lambda: self._run_command("бросить кубик"))
        self.check_choice = QComboBox()
        self.check_choice.setAccessibleName("Характеристика для проверки")
        for command, ability in CHECK_COMMANDS.items():
            self.check_choice.addItem(ABILITY_NAMES[ability], command)
        dice.addWidget(self.check_choice)
        self._panel_button(
            dice,
            "Проверить характеристику",
            lambda: self._run_command(self.check_choice.currentData()),
        )
        self.roll_history = QPlainTextEdit()
        self.roll_history.setReadOnly(True)
        self.roll_history.setFont(self.journal.font())
        self.roll_history.setAccessibleName("История бросков")
        dice.addWidget(self.roll_history, 1)
        self.roll_summary = plain_label()
        dice.addWidget(self.roll_summary)

        guide = self._episode_page("Как играть")
        guide.addWidget(
            plain_label(
                "Создайте героя, опишите его прошлое и пожелания к миру. Мастер "
                "выберет место появления и сюжетные зацепки. "
                "Для ИИ-генерации включите и настройте мастера до создания героя. "
                "Для игры через чат нужен облачный мастер. "
                "Действуйте через чат; важные сведения записывайте в Дневник."
            )
        )
        guide.addWidget(
            plain_label(
                "Продолжение: сохраните игру в одну из трёх ячеек. При следующем запуске "
                "выберите загрузку. Экспорт .txt предназначен для чтения; "
                "он не восстанавливает игру."
            )
        )
        guide.addWidget(
            plain_label(
                "Управление: Enter — отправить; ↑/↓ — история ввода; "
                "Ctrl+S/O — сохранить/загрузить; "
                "Ctrl+F — поиск; Ctrl+E — экспорт; Ctrl+M — меню; "
                "F11 — полный экран, Esc — выход из него."
            )
        )
        guide.addWidget(
            plain_label(
                "Товары открываются при разговоре с торговцем рядом; панель "
                "противника — при взаимодействии с целью. "
                "Ресурсы и результаты проверяет движок. Рабочая память SQLite и "
                "личные заметки сохраняются отдельно от полного текста истории."
            )
        )
        guide.addWidget(
            plain_label(
                "Следующие этапы: полные правила боя SRD, инициатива, классы/навыки/магия, "
                "отношения NPC, формальные конфликты и исследовательский режим. "
                "Их механики ещё не реализованы. Мастер использует выбранную локальную "
                "модель или необязательный API."
            )
        )
        guide.addWidget(
            plain_label(
                "Рассказчик: осмотрите сцену («что я вижу?»), введите действие и "
                "прочтите итог в журнале. Справа — риск выбранного действия и отдельный "
                "разбор кубиков: выпавшее число, бонус, сумма, порог и последствия. "
                "Выбор прошлой записи ничего не переигрывает. "
                "Игровые действия выполняются через чат. Меню и сохранения доступны отдельно."
            )
        )
        self._panel_button(guide, "О программе и лицензии", self._show_about)
        guide.addStretch()

        install_combat_panel(self)
        install_narrator_panels(self)
        inventory_layout = self.inventory_label.parentWidget().layout()
        self.inventory_table = readonly_table(["Предмет", "Количество", "Назначение"])
        self.inventory_table.setAccessibleName("Предметы героя")
        inventory_layout.insertWidget(1, self.inventory_table, 1)
        self.study_button = QPushButton("Изучить дорожный учебник")
        self.study_button.setProperty("game_action", True)
        self.study_button.setVisible(self._legacy_controls)
        self.study_button.clicked.connect(lambda: self._run_command("изучить учебник"))
        inventory_layout.insertWidget(2, self.study_button)
        hero_layout = self.tabs.widget(1).layout()
        self.cart_button = QPushButton("Помочь разгрузить телегу у ворот")
        self.cart_button.setProperty("game_action", True)
        self.cart_button.setVisible(self._legacy_controls)
        self.cart_button.clicked.connect(lambda: self._run_command("помочь разгрузить телегу"))
        hero_layout.insertWidget(2, self.cart_button)
        self.development_log = QPlainTextEdit()
        self.development_log.setReadOnly(True)
        self.development_log.setAccessibleName("Журнал развития")
        self.development_log.setMaximumHeight(100)
        hero_layout.insertWidget(3, self.development_log)

        # A compact picker replaces a growing row of tabs without changing page indices.
        self.tabs.tabBar().hide()
        navigation_row = QHBoxLayout()
        self.navigation = QComboBox()
        self.navigation.setAccessibleName("Раздел игры")
        install_catalog_panel(self)
        from rpg_vkr.ui.adventure_panel import install_adventure_panel

        install_adventure_panel(self)
        self._persist_campaign()
        if not self._legacy_controls:
            for index in reversed(range(self.tabs.count())):
                if self.tabs.tabText(index) in {
                    "Жители",
                    "Лавка",
                    "Схватка",
                    "Команды",
                    "Кубики",
                    "Задание",
                }:
                    page = self.tabs.widget(index)
                    self.tabs.removeTab(index)
                    page.hide()
        order = [
            "Главное меню",
            "Приключение",
            "Герой",
            "Инвентарь",
            "Дневник",
            "Задание",
            "Карта",
            "Жители",
            "Схватка",
            "Лавка",
            "Кубики",
            "Память мира",
            "Рассказчик",
            "Каталог мира",
            "Хроники мира",
            "Команды",
            "Сохранения",
            "Настройки",
            "Как играть",
        ]
        for name in order:
            for index in range(self.tabs.count()):
                if self.tabs.tabText(index) == name:
                    self.navigation.addItem(name, index)
        navigation_row.addWidget(QLabel("Раздел:"))
        navigation_row.addWidget(self.navigation, 1)
        self._panel_button(navigation_row, "К игре", self.resume_session)
        if not self._legacy_controls:
            self.chronicles_shortcut = self._panel_button(
                navigation_row, "Хроники", lambda: self.open_section("Хроники мира")
            )
            self.compact_rolls = self._panel_button(
                navigation_row, "Кубики", self.show_compact_rolls
            )
            self.compact_rolls.hide()
        self._panel_button(navigation_row, "Меню", lambda: self.open_section("Главное меню"))
        self.navigation_bar = QWidget()
        self.navigation_bar.setLayout(navigation_row)
        root_layout.insertWidget(root_layout.indexOf(self.tabs), self.navigation_bar)
        self.navigation.currentIndexChanged.connect(
            lambda index: self.tabs.setCurrentIndex(self.navigation.itemData(index))
        )
        self.tabs.currentChanged.connect(self._sync_navigation)
        self._sync_navigation(self.tabs.currentIndex())

        view = self.menuBar().addMenu("Вид")
        self.fullscreen_action = QAction("Полный экран", self)
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.setShortcut("F11")
        self.fullscreen_action.triggered.connect(self._toggle_fullscreen)
        view.addAction(self.fullscreen_action)
        for label, shortcut, callback in (
            ("Главное меню", "Ctrl+M", lambda: self.open_section("Главное меню")),
            ("Вернуться из полного экрана", "Esc", self._leave_fullscreen),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            view.addAction(action)
        self._refresh_episode_panels()

    def open_section(self, name: str) -> None:
        if name == "Каталог мира" and not self._legacy_controls:
            name = "Хроники мира"
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                return
        if name == "Схватка":
            from rpg_vkr.ui.context_actions import show_encounter

            target = self._session.combat.active or self.combat_targets.currentData()
            if target:
                self.resume_session()
                show_encounter(self, target)
            return
        if name == "Лавка":
            from rpg_vkr.ui.context_actions import show_trade

            if self._session.actor_is_here("merchant") and self._session.world.trading:
                show_trade(self, "merchant")
            return
        raise ValueError(f"Unknown UI section: {name}")

    def _sync_navigation(self, index: int) -> None:
        self.navigation.blockSignals(True)
        self.navigation.setCurrentIndex(self.navigation.findData(index))
        self.navigation.blockSignals(False)
        if hasattr(self, "resolution_panel"):
            from rpg_vkr.ui.theme import sync_chrome

            sync_chrome(self, index)

    def resume_session(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.action_input.setFocus()
        QTimer.singleShot(0, self.journal, self.journal.ensureCursorVisible)

    def _talk_to_resident(self) -> None:
        command = ("поговорить со стражником", "поговорить с жительницей", "поговорить")[
            self.resident_list.currentRow()
        ]
        self._run_command(command)

    def _refresh_resident(self) -> None:
        row = self.resident_list.currentRow()
        if row < 0:
            return
        name, location, description = RESIDENTS[row]
        if row == 2 and self._session.world.location != "market":
            description = "Найдите рынок и подойдите к торговцу, чтобы узнать о товаре."
        actor_id = ("guard", "villager", "merchant")[row]
        actor = self._session.combat.actor(actor_id)
        present = (
            self._session.world.location == location
            and actor.hp > 0
            and actor.disposition == "neutral"
            and self._session.combat.active is None
            and self._session.world.hp > 0
        )
        if actor.hp == 0:
            description += " Персонаж повержен; взаимодействие недоступно."
        elif actor.disposition == "hostile":
            description += " Персонаж враждебен; мирное общение недоступно."
        self.resident_description.setText(
            f"{name}: {description}\n"
            + ("Вы в одном месте." if present else "Сначала перейдите в его локацию.")
        )
        self.resident_talk.setEnabled(present)
        self.resident_help.setEnabled(present and row == 1)
        self.resident_quest.setEnabled(
            present and row == 1 and self._session.world.quest == "available"
        )

    def _refresh_episode_panels(self) -> None:
        if not hasattr(self, "inventory_table"):
            return
        state = self._session.world
        hostiles = [
            actor.id for actor in self._session.combat.actors if actor.disposition == "hostile"
        ]
        if self._session.catalog:
            hostiles += [
                e.id
                for e in self._session.catalog.entities
                if (e.state or {}).get("disposition") == "hostile"
            ]
        self.journal.set_hostiles(hostiles)
        refresh_combat_panel(self)
        peace = self._session.combat.active is None and state.hp > 0
        merchant = self._session.combat.actor("merchant")
        villager = self._session.combat.actor("villager")
        merchant_available = merchant.hp > 0 and merchant.disposition == "neutral" and peace
        villager_available = villager.hp > 0 and villager.disposition == "neutral" and peace
        progress = self._session.progress
        if self._legacy_controls:
            self.resume_button.setText(
                "Вернуться к текущему герою" if progress.enabled else "Открыть учебную песочницу"
            )
        self.study_button.setEnabled(progress.enabled and not progress.practiced("book") and peace)
        self.cart_button.setEnabled(
            progress.enabled
            and state.location == "gate"
            and not progress.practiced("cart")
            and peace
        )
        self.development_log.setPlainText(
            "\n".join(describe_award(event) for event in progress.events)
            or "Журнал развития пуст. Для обучения создайте героя и выполните значимое действие."
        )
        self.home_summary.setText(
            f"Текущий герой: {self._session.character.name}. Место: {LOCATIONS[state.location]}. "
            "Загрузка и новый герой заменяют текущую сессию только после обычного подтверждения."
        )
        if not self._legacy_controls:
            self.home_summary.setText(
                f"{self._session.character.name} · {self._session.current_place_name}"
                if progress.enabled or self._session.turns
                else "Новое приключение ждёт своего героя"
            )
        self.map_location.setText("Вы здесь: " + LOCATIONS[state.location])
        for location, button in self.travel_buttons.items():
            known = location != "market" or state.market_known
            button.setText(LOCATIONS[location] if known else "Неизвестное место")
            button.setEnabled(known and location != state.location and peace)
        self.ask_market.setEnabled(
            state.location == "gate"
            and not state.market_known
            and peace
            and self._session.combat.actor("guard").disposition == "neutral"
            and self._session.combat.actor("guard").hp > 0
        )
        self.quick_buttons["идти на рынок"].setEnabled(state.market_known and peace)
        self.quick_buttons["подойти к торговцу"].setEnabled(
            state.location == "market" and merchant_available
        )
        self.quick_buttons["исследовать дорогу"].setEnabled(
            state.location == "road" and not state.explored and peace
        )
        self.quick_buttons["взять поручение"].setEnabled(
            state.location == "gate" and state.quest == "available" and villager_available
        )
        self.quick_buttons["доставить корзину"].setEnabled(
            state.location == "market" and state.quest == "active" and peace
        )
        for row, (name, _location, _) in enumerate(RESIDENTS):
            visible_name = name if row != 2 or state.location == "market" else "Житель рынка"
            actor_id = ("guard", "villager", "merchant")[row]
            actor = self._session.combat.actor(actor_id)
            mark = (
                " [" + disposition_label(actor) + "]"
                if not actor.hp or actor.disposition == "hostile"
                else ""
            )
            self.resident_list.item(row).setText(visible_name + mark)
            self.resident_list.item(row).setForeground(QBrush(self.journal.actor_colour(actor_id)))
        self.shop_travel.setEnabled(state.market_known and state.location != "market" and peace)
        self.approach_merchant.setEnabled(
            state.location == "market" and not state.trading and merchant_available
        )
        self.exploration_status.setText(
            "Дорога уже исследована."
            if state.explored
            else "Дорога ещё не исследована: возможны находка или потеря здоровья."
        )
        self.map_explore.setEnabled(state.location == "road" and not state.explored and peace)
        self._refresh_resident()
        conversation = next(
            (
                turn.text
                for turn in reversed(self._session.turns)
                if (turn.intent or turn.action).casefold().strip()
                in (
                    "поговорить",
                    "поговорить со стражником",
                    "поговорить с жительницей",
                    "помочь",
                    "взять поручение",
                    "подойти к торговцу",
                    "продать бинт",
                )
            ),
            "Разговора пока не было. Выберите жителя в текущем месте.",
        )
        self.resident_reply.setPlainText(conversation)
        visible_trade = state.location == "market" and state.trading and merchant_available
        self.shop_summary.setText(
            f"Ваше золото: {state.gold}; ваши бинты: {state.bandages}. "
            + (
                f"Торговец предлагает бинты. В наличии: {state.shop_stock}."
                if visible_trade
                else "Торговец повержен. Лавка недоступна."
                if merchant.hp == 0
                else "Торговец враждебен. Торговля закрыта."
                if merchant.disposition == "hostile"
                else "Ассортимент ещё не показан. Найдите рынок и подойдите к торговцу."
            )
        )
        self.shop_buy.setVisible(visible_trade and self._legacy_controls)
        self.shop_sell.setVisible(visible_trade and self._legacy_controls)
        self.shop_buy.setEnabled(visible_trade and state.gold >= 3 and state.shop_stock > 0)
        # The NPC's wallet stays private. Refusal to buy is revealed by the dialogue.
        self.shop_sell.setEnabled(visible_trade and state.bandages > 0)
        reasons = []
        if not visible_trade:
            reasons.append(
                "Торговец враждебен или повержен; торговля недоступна."
                if not merchant.hp or merchant.disposition == "hostile"
                else "Сначала завершите схватку."
                if not peace
                else "Торговля доступна после подхода к торговцу на рынке."
            )
        else:
            if state.gold < 3:
                reasons.append("Для покупки не хватает золота.")
            if not state.shop_stock:
                reasons.append("В предложенном ассортименте больше нет бинтов.")
            if not state.bandages:
                reasons.append("У вас нет бинтов для продажи.")
        trade_turn = next(
            (
                turn.text
                for turn in reversed(self._session.turns)
                if (turn.intent or turn.action).casefold().strip()
                in ("подойти к торговцу", "торговля", "купить бинт", "продать бинт")
            ),
            "",
        )
        self.shop_reply.setPlainText(trade_turn if visible_trade else "")
        self.shop_reason.setText(" ".join(reasons) or "Выберите покупку или продажу одного бинта.")
        items = []
        if state.bandages:
            items.append(("Бинт", str(state.bandages), "Восстановить до 4 ОЗ"))
        if state.basket:
            items.append(("Корзина поручения", "1", "Доставить на рынок"))
        items.extend(
            (name, str(quantity), purpose)
            for name, quantity, purpose in self._session.extra_inventory_rows
        )
        self.inventory_table.setRowCount(len(items))
        for row, values in enumerate(items):
            for column, value in enumerate(values):
                self.inventory_table.setItem(row, column, QTableWidgetItem(value))
        rolls = [
            (roll, turn)
            for turn in self._session.turns
            for roll in (
                turn.inspection.rolls
                if turn.inspection
                else (
                    turn.combat.outcome.rolls
                    if turn.combat
                    else ((turn.roll,) if turn.roll else ())
                )
            )
        ]
        self.roll_history.setPlainText(
            "\n\n".join(
                f"#{roll.index} · кубик {roll.value} · {turn.action}" for roll, turn in rolls[-100:]
            )
        )
        self.roll_summary.setText(
            f"Бросков в сессии: {len(rolls)}. Показаны последние 100; "
            "разбор последних 100 действий — в панели справа."
        )
        refresh_resolution_panel(self)
        refresh_narrator_panels(self)
        refresh_catalog_panel(self)

    def _toggle_fullscreen(self, checked: bool) -> None:
        self.showFullScreen() if checked else self.showNormal()

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.fullscreen_action.setChecked(False)
