"""A physical merchant's finite stock and equipment, quoted by Session in copper."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rpg_vkr.domain.gameplay_v2 import name
from rpg_vkr.domain.trade import merchant


class CopperTradeDialog(QDialog):
    def __init__(self, window, actor_id):
        super().__init__(window)
        self.window, self.actor_id, self.session = window, actor_id, window._session
        self.setWindowTitle("Торговля · медные монеты")
        self.resize(660, 480)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.mode = QComboBox()
        self.mode.addItems(["Купить у торговца", "Продать торговцу"])
        layout.addWidget(self.mode)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Предмет", "Количество"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.table)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1000)
        layout.addWidget(self.quantity)
        self.execute = QPushButton("Проверить выбранную сделку")
        layout.addWidget(self.execute)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.table.currentCellChanged.connect(lambda *_: self.update_quote())
        self.quantity.valueChanged.connect(self.update_quote)
        self.execute.clicked.connect(self.submit)
        self.refresh()

    def selection(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.rows):
            raise ValueError("Выберите предмет.")
        id, _, _, equipment = self.rows[row]
        operation = "buy" if self.mode.currentIndex() == 0 else "sell"
        if equipment:
            if self.quantity.value() != 1:
                raise ValueError("Этот экземпляр передаётся по одному.")
            return operation, {"merchant": self.actor_id, "item": id}
        return "trade_world", {
            "merchant": self.actor_id,
            "item": id,
            "operation": operation,
            "quantity": self.quantity.value(),
        }

    def refresh(self):
        session = self.window._session
        if session is not self.session or not session.actor_is_here(self.actor_id):
            self.close()
            return
        try:
            merchant(session.catalog, self.actor_id)
        except ValueError:
            self.close()
            return
        owner = self.actor_id if self.mode.currentIndex() == 0 else "hero"
        scene, state = session.interaction_state(), session.gameplay
        self.rows = [
            (t.id, t.name, t.quantity, False)
            for t in scene.things
            if t.resource != "gold" and scene.root_holder(t) == owner
        ]
        self.rows.extend((i["id"], name(i), 1, True) for i in state["items"] if i["owner"] == owner)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for row, (_, title, quantity, _) in enumerate(self.rows):
            self.table.setItem(row, 0, QTableWidgetItem(title))
            self.table.setItem(row, 1, QTableWidgetItem(str(quantity)))
        self.table.blockSignals(False)
        if self.rows:
            self.table.selectRow(0)
        self.status.setText(
            f"Ваши деньги: {session.world.gold * 100 + state['copper']} медных. "
            "Цена учитывает прочность и размер партии."
        )
        self.update_quote()

    def update_quote(self):
        self.execute.setEnabled(False)
        if self.window._session is not self.session:
            self.close()
            return
        try:
            command, args = self.selection()
            result = self.session.preview_gameplay(command, args)
            receipt = result.get("transaction")
            if receipt is None:
                # Fixed catalog equipment still uses the original resolver's price calculation.
                price = abs(
                    (result["world"]["gold"] * 100 + result["state"]["copper"])
                    - (self.session.world.gold * 100 + self.session.gameplay["copper"])
                )
            else:
                price = receipt["price_cp"]
        except (ValueError, TypeError, KeyError) as error:
            self.execute.setText("Сделка недоступна")
            self.status.setText(str(error))
            return
        self.status.setText(
            f"Ваши деньги: {self.session.world.gold * 100 + self.session.gameplay['copper']} "
            "медных. "
            + (
                f"Товар: {receipt['base_price_cp']} медных; "
                f"пошлина 5%: {receipt['duty_cp']} медных. Итог: {price}."
                if receipt and receipt.get("duty_cp")
                else "Цена учитывает прочность и размер партии."
            )
        )
        self.execute.setText(
            ("Купить" if self.mode.currentIndex() == 0 else "Продать") + f" за {price} медных"
        )
        self.execute.setEnabled(True)

    def submit(self):
        if self.window._session is not self.session:
            self.close()
            return
        try:
            self.selection()
            id, title, _, _ = self.rows[self.table.currentRow()]
            self.session.submit_trade(
                ("Покупаю " if self.mode.currentIndex() == 0 else "Продаю ") + title,
                self.actor_id,
                id,
                "buy" if self.mode.currentIndex() == 0 else "sell",
                self.quantity.value(),
            )
        except (ValueError, TypeError, KeyError) as error:
            self.status.setText(str(error))
            return
        self.window._dirty = True
        self.window._refresh_character()
        self.window._render_journal()
        self.refresh()
