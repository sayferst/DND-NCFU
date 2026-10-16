"""Complete screens for the existing episode; all mutations go through Session."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
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
from rpg_vkr.domain.world import LOCATIONS

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
        layout.addWidget(button)
        return button

    def _build_episode_panels(self, root_layout) -> None:
        menu = self._episode_page("Главное меню")
        menu.addWidget(plain_label("Пограничье · Доставка на рынок"))
        self.home_summary = plain_label()
        menu.addWidget(self.home_summary)
        self.resume_button = self._panel_button(
            menu, "Вернуться к текущей сессии", self.resume_session
        )
        self._panel_button(menu, "Новый герой…", self.new_character)
        self._panel_button(menu, "Загрузить сохранение…", self.choose_load)
        self._panel_button(menu, "Сохранить текущую сессию…", self.quick_save)
        self._panel_button(menu, "Настройки", lambda: self.open_section("Настройки"))
        self._panel_button(menu, "Как играть", lambda: self.open_section("Как играть"))
        self._panel_button(menu, "Выйти", self.close)
        menu.addWidget(plain_label("Меню не сбрасывает игру. Автосохранения нет."))
        menu.addStretch()

        map_layout = self._episode_page("Карта")
        map_layout.addWidget(
            plain_label(
                "Три места эпизода: ворота, дорога и рынок. Переход бесплатный. "
                "Здесь нет расстояний, скрытых областей или случайных встреч."
            )
        )
        self.ask_market = self._panel_button(
            map_layout,
            "Узнать дорогу у стражника",
            lambda: self._run_command("узнать дорогу на рынок"),
        )
        self.map_location = plain_label()
        map_layout.addWidget(self.map_location)
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
                "d20 и базовые проверки характеристик против сложности 10. "
                "Проверки в этой панели не меняют ресурсы мира."
            )
        )
        self._panel_button(dice, "Бросить d20", lambda: self._run_command("бросить d20"))
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
                "Начало: возьмите поручение у ворот, сходите на рынок и доставьте корзину. "
                "Дорогу можно исследовать один раз. У торговца можно узнать об ассортименте. "
                "Все действия записываются в журнал приключения."
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
                "Работает: герой, ресурсы, три места, поручение, лавка, бинты, "
                "d20, базовые проверки, "
                "журнал и сохранения. Рассказчик автономный, понимает команды из справочника."
            )
        )
        guide.addWidget(
            plain_label(
                "Следующие этапы: бой и инициатива, классы/навыки/магия/экипировка, "
                "отношения NPC, формальные конфликты и исследовательский режим. "
                "Их механики ещё не реализованы. Игра не использует LLM или платные API."
            )
        )
        self._panel_button(guide, "О программе и лицензии", self._show_about)
        guide.addStretch()

        inventory_layout = self.inventory_label.parentWidget().layout()
        self.inventory_table = readonly_table(["Предмет", "Количество", "Назначение"])
        self.inventory_table.setAccessibleName("Предметы героя")
        inventory_layout.insertWidget(1, self.inventory_table, 1)

        # A compact picker replaces a growing row of tabs without changing page indices.
        self.tabs.tabBar().hide()
        navigation_row = QHBoxLayout()
        self.navigation = QComboBox()
        self.navigation.setAccessibleName("Раздел игры")
        order = [7, 0, 1, 2, 3, 8, 9, 10, 11, 4, 6, 5, 12]
        for index in order:
            self.navigation.addItem(self.tabs.tabText(index), index)
        navigation_row.addWidget(QLabel("Раздел:"))
        navigation_row.addWidget(self.navigation, 1)
        self._panel_button(navigation_row, "К игре", self.resume_session)
        self._panel_button(navigation_row, "Меню", lambda: self.open_section("Главное меню"))
        root_layout.insertLayout(root_layout.indexOf(self.tabs), navigation_row)
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
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                return
        raise ValueError(f"Unknown UI section: {name}")

    def _sync_navigation(self, index: int) -> None:
        self.navigation.blockSignals(True)
        self.navigation.setCurrentIndex(self.navigation.findData(index))
        self.navigation.blockSignals(False)

    def resume_session(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.action_input.setFocus()

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
        present = self._session.world.location == location
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
        self.home_summary.setText(
            f"Текущий герой: {self._session.character.name}. Место: {LOCATIONS[state.location]}. "
            "Загрузка и новый герой заменяют текущую сессию только после обычного подтверждения."
        )
        self.map_location.setText("Вы здесь: " + LOCATIONS[state.location])
        for location, button in self.travel_buttons.items():
            known = location != "market" or state.market_known
            button.setText(LOCATIONS[location] if known else "Неизвестное место")
            button.setEnabled(known and location != state.location)
        self.ask_market.setEnabled(state.location == "gate" and not state.market_known)
        self.quick_buttons["идти на рынок"].setEnabled(state.market_known)
        self.quick_buttons["подойти к торговцу"].setEnabled(state.location == "market")
        self.quick_buttons["исследовать дорогу"].setEnabled(
            state.location == "road" and not state.explored
        )
        self.quick_buttons["взять поручение"].setEnabled(
            state.location == "gate" and state.quest == "available"
        )
        self.quick_buttons["доставить корзину"].setEnabled(
            state.location == "market" and state.quest == "active"
        )
        for row, (name, _location, _) in enumerate(RESIDENTS):
            visible_name = name if row != 2 or state.location == "market" else "Житель рынка"
            self.resident_list.item(row).setText(visible_name)
        self.shop_travel.setEnabled(state.market_known and state.location != "market")
        self.approach_merchant.setEnabled(state.location == "market" and not state.trading)
        self.exploration_status.setText(
            "Дорога уже исследована."
            if state.explored
            else "Дорога ещё не исследована: возможны находка или потеря здоровья."
        )
        self.map_explore.setEnabled(state.location == "road" and not state.explored)
        self._refresh_resident()
        conversation = next(
            (
                turn.text
                for turn in reversed(self._session.turns)
                if turn.action.casefold().strip()
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
        visible_trade = state.location == "market" and state.trading
        self.shop_summary.setText(
            f"Ваше золото: {state.gold}; ваши бинты: {state.bandages}. "
            + (
                f"Торговец предлагает бинты. В наличии: {state.shop_stock}."
                if visible_trade
                else "Ассортимент ещё не показан. Найдите рынок и подойдите к торговцу."
            )
        )
        self.shop_buy.setVisible(visible_trade)
        self.shop_sell.setVisible(visible_trade)
        self.shop_buy.setEnabled(visible_trade and state.gold >= 3 and state.shop_stock > 0)
        # The NPC's wallet stays private. Refusal to buy is revealed by the dialogue.
        self.shop_sell.setEnabled(visible_trade and state.bandages > 0)
        reasons = []
        if not visible_trade:
            reasons.append("Торговля доступна после подхода к торговцу на рынке.")
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
                if turn.action.casefold().strip()
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
        self.inventory_table.setRowCount(len(items))
        for row, values in enumerate(items):
            for column, value in enumerate(values):
                self.inventory_table.setItem(row, column, QTableWidgetItem(value))
        rolls = [turn for turn in self._session.turns if turn.roll is not None]
        self.roll_history.setPlainText(
            "\n\n".join(f"#{turn.roll.index} · {turn.text}" for turn in rolls[-100:])
        )
        self.roll_summary.setText(
            f"Бросков в сессии: {len(rolls)}. Показаны последние 100; полная история — в журнале."
        )

    def _toggle_fullscreen(self, checked: bool) -> None:
        self.showFullScreen() if checked else self.showNormal()

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.fullscreen_action.setChecked(False)
