"""Contextual merchant and encounter windows, backed by actual session records."""

import re

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rpg_vkr.domain.catalog_actions import ActorAttempt
from rpg_vkr.domain.combat import ACTORS, health_description
from rpg_vkr.domain.trade import merchant, transact
from rpg_vkr.storage.catalog import CatalogIndex


def refresh_context(window):
    if getattr(window, "_context_session", None) is not window._session:
        window._context_session = window._session
        window._context_target_id = ""
    for attr in ("_trade_dialog", "_encounter_dialog"):
        dialog = getattr(window, attr, None)
        if dialog:
            dialog.refresh()
    session = window._session
    if not session.turns or getattr(window, "_context_seen", None) == (
        id(session),
        len(session.turns),
    ):
        return
    window._context_seen = (id(session), len(session.turns))
    turn = session.turns[-1]
    if isinstance(turn.catalog, ActorAttempt) and turn.catalog.operation == "attack":
        show_encounter(window, turn.catalog.target_id)
    elif turn.combat and turn.actor_id:
        show_encounter(window, turn.actor_id)
    elif turn.trade:
        show_trade(window, turn.trade.merchant_id)
    elif re.search(
        r"ассортимент|торг\w*|товар\w*|купить|куплю|продать|продам", turn.action.casefold()
    ):
        scene = session.interaction_state()
        candidates = []
        for actor in scene.actor_refs:
            if actor.place != scene.current:
                continue
            if actor.id == "merchant" and session.world.trading:
                candidates.append(actor.id)
            elif session.catalog:
                try:
                    merchant(session.catalog, actor.id)
                except ValueError:
                    continue
                candidates.append(actor.id)
        if len(candidates) == 1:
            show_trade(window, candidates[0])


def show_trade(window, actor_id):
    old = getattr(window, "_trade_dialog", None)
    if old:
        old.close()
        old.deleteLater()
    dialog = TradeDialog(window, actor_id)
    window._trade_dialog = dialog
    window._context_target_id = actor_id
    dialog.show()


class TradeDialog(QDialog):
    def __init__(self, window, actor_id):
        super().__init__(window)
        self.window, self.actor_id = window, actor_id
        self.session = window._session
        self.setWindowTitle("Разговор с торговцем · товары")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.mode = QComboBox()
        self.mode.addItems(["Купить у торговца", "Продать торговцу"])
        layout.addWidget(self.mode)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Товар", "Количество", "Цена за единицу"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1000)
        self.quantity.valueChanged.connect(lambda _: self.update_quote())
        self.table.currentCellChanged.connect(lambda *_: self.update_quote())
        self.execute = QPushButton("Совершить выбранную сделку")
        self.execute.clicked.connect(self.submit)
        row.addWidget(self.quantity)
        row.addWidget(self.execute)
        layout.addLayout(row)
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        self.mode.currentIndexChanged.connect(lambda _: self.refresh())
        self.refresh()

    def refresh(self):
        session = self.window._session
        if session is not self.session:
            self.close()
            return
        if not session.actor_is_here(self.actor_id):
            self.close()
            return
        buying = self.mode.currentIndex() == 0
        self.rows = []
        if self.actor_id == "merchant" and not session.generated_world:
            if (
                not session.world.trading
                or session.combat.actor("merchant").disposition == "hostile"
            ):
                self.close()
                return
            self.rows = [
                (
                    "legacy_bandages",
                    "Бинт",
                    session.world.shop_stock if buying else session.world.bandages,
                    3 if buying else 1,
                )
            ]
        elif session.catalog:
            try:
                merchant(session.catalog, self.actor_id)
            except ValueError:
                self.close()
                return
            scene = session.interaction_state()
            index = CatalogIndex(session)
            try:
                for item in scene.things:
                    if item.resource == "gold" or scene.root_holder(item) != (
                        self.actor_id if buying else "hero"
                    ):
                        continue
                    value = index.lookup(item.id, public=False)
                    price = value["definition"]["price_cp"] if value else None
                    if price is None or price < 1:
                        continue
                    cost = (price + 99) // 100 if buying else price // 200
                    self.rows.append((item.id, item.name, item.quantity, cost))
            finally:
                index.close()
        self.table.setRowCount(len(self.rows))
        for i, (_, name, quantity, price) in enumerate(self.rows):
            for col, value in enumerate(
                (
                    name,
                    str(quantity),
                    str(price) + " золотых" if price else "партией; см. итог сделки",
                )
            ):
                self.table.setItem(i, col, QTableWidgetItem(value))
        if self.rows:
            self.table.selectRow(0)
        self.execute.setEnabled(bool(self.rows))
        self.status.setText(
            f"Ваше золото: {session.world.gold}. Показаны товары текущего собеседника. "
            "Цена продажи — половина базовой с округлением вниз."
        )
        self.update_quote()

    def update_quote(self):
        if self.window._session is not self.session:
            self.close()
            return
        row = self.table.currentRow()
        if not hasattr(self, "rows") or not 0 <= row < len(self.rows):
            self.execute.setEnabled(False)
            return
        operation = "buy" if self.mode.currentIndex() == 0 else "sell"
        session = self.window._session
        if self.actor_id == "merchant" and not session.generated_world:
            self.execute.setEnabled(self.quantity.value() == 1)
            self.execute.setText(
                "Купить за 3 золотых" if operation == "buy" else "Продать за 1 золотую"
            )
            return
        try:
            _, _, record = transact(
                session.catalog,
                session.interaction_state(),
                session.world,
                self.actor_id,
                self.rows[row][0],
                operation,
                self.quantity.value(),
                len(session.turns) + 1,
                "player-ui",
                session.catalog_aliases,
            )
        except (ValueError, TypeError, KeyError) as error:
            self.execute.setEnabled(False)
            self.status.setText("Сделка недоступна: " + str(error))
            return
        self.execute.setEnabled(True)
        self.execute.setText(
            ("Купить за " if operation == "buy" else "Продать за ")
            + str(record.price_gold)
            + " золотых"
        )

    def submit(self):
        if self.window._session is not self.session:
            self.close()
            return
        row = self.table.currentRow()
        if not 0 <= row < len(self.rows):
            return
        id, name, _, _ = self.rows[row]
        session = self.window._session
        operation = "buy" if self.mode.currentIndex() == 0 else "sell"
        try:
            if self.actor_id == "merchant" and not session.generated_world:
                if self.quantity.value() != 1:
                    raise ValueError("Старый торговец продаёт по одному бинту за сделку.")
                session.submit(
                    "купить бинт" if operation == "buy" else "продать бинт", origin="system"
                )
            else:
                _, _, quote = transact(
                    session.catalog,
                    session.interaction_state(),
                    session.world,
                    self.actor_id,
                    id,
                    operation,
                    self.quantity.value(),
                    len(session.turns) + 1,
                    "player-ui",
                    session.catalog_aliases,
                )
                session.submit_trade(
                    ("Покупаю " if operation == "buy" else "Продаю ") + name,
                    self.actor_id,
                    id,
                    operation,
                    self.quantity.value(),
                )
        except (ValueError, TypeError, KeyError) as error:
            self.status.setText("Сделка не выполнена: " + str(error))
            return
        self.window._dirty = True
        self.window._refresh_character()
        self.window._render_journal()
        from rpg_vkr.ui.narrator_panel import request_narration

        if self.window.enable_local_narrator.isChecked():
            request_narration(self.window)


def show_encounter(window, target):
    old = getattr(window, "_encounter_dialog", None)
    if old:
        old.close()
        old.deleteLater()
    window._encounter_dialog = EncounterDialog(window, target)
    window._context_target_id = target
    window._encounter_dialog.show()


class EncounterDialog(QDialog):
    def __init__(self, window, target):
        super().__init__(window)
        self.window, self.target = window, target
        self.session = window._session
        self.setWindowTitle("Выбранная цель · схватка")
        self.resize(540, 220)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.action = QLineEdit()
        self.action.setPlaceholderText("Опишите следующее действие своими словами")
        layout.addWidget(self.action)
        self.send = QPushButton("Отправить действие")
        self.send.clicked.connect(self.submit)
        self.action.returnPressed.connect(self.submit)
        layout.addWidget(self.send)
        self.refresh()

    def refresh(self):
        session = self.window._session
        if session is not self.session:
            self.close()
            return
        if not session.actor_is_here(self.target):
            self.close()
            return
        actor = next(a for a in session.interaction_state().actor_refs if a.id == self.target)
        if self.target in ACTORS:
            description = health_description(session.combat.actor(self.target))
        else:
            e = next(e for e in session.catalog.entities if e.id == self.target)
            hp = (e.state or {}).get("hp", 1)
            description = (
                "погиб"
                if (e.state or {}).get("life") == "dead"
                else "повержен"
                if hp == 0
                else "на ногах"
            )
        self.status.setText(
            actor.name
            + ": "
            + description
            + f". Ваше здоровье: {session.world.hp}/{session.world.max_hp}. "
            + "Исход действия определяет движок; расчёт остаётся справа в основном окне."
        )
        self.send.setEnabled(session.world.hp > 0)

    def submit(self):
        if self.window._session is not self.session:
            self.close()
            return
        text = self.action.text().strip()
        if not text:
            return
        self.window.action_input.setText(text)
        self.window.submit_action()
        if not self.window.action_input.text():
            self.action.clear()
