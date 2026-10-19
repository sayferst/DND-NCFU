"""Read-only browsing and explicit SQLite export; no ready-made game replies."""

import json
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.domain.catalog import CATEGORIES
from rpg_vkr.storage.catalog import CatalogIndex


def install_catalog_panel(window):
    page = QWidget()
    layout = QVBoxLayout(page)
    hint = QLabel(
        "Тип — описание возможной вещи; экземпляр — конкретный объект в кампании. "
        "Новые записи мастер добавляет при развитии сцены. Частные кошельки и точные "
        "параметры NPC здесь скрыты. Экспорт содержит полное состояние кампании."
    )
    hint.setWordWrap(True)
    layout.addWidget(hint)
    row = QHBoxLayout()
    window.catalog_category = QComboBox()
    window.catalog_category.addItem("Все разделы", "")
    for key, name in CATEGORIES.items():
        window.catalog_category.addItem(name, key)
    window.catalog_mode = QComboBox()
    window.catalog_mode.addItems(["Экземпляры в кампании", "Типы из справочника"])
    window.catalog_search = QLineEdit()
    window.catalog_search.setPlaceholderText("Название или ID")
    row.addWidget(window.catalog_category)
    row.addWidget(window.catalog_mode)
    row.addWidget(window.catalog_search, 1)
    layout.addLayout(row)
    window.catalog_table = QTableWidget(0, 3)
    window.catalog_table.setHorizontalHeaderLabels(["ID", "Название", "Количество / вид"])
    window.catalog_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    window.catalog_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    window.catalog_table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(window.catalog_table, 1)
    window.catalog_detail = QPlainTextEdit()
    window.catalog_detail.setReadOnly(True)
    window.catalog_detail.setMaximumHeight(230)
    layout.addWidget(window.catalog_detail)
    window.catalog_export = QPushButton("Экспорт кампании и каталога в SQLite…")
    layout.addWidget(window.catalog_export)
    window.catalog_status = QLabel()
    window.catalog_status.setWordWrap(True)
    layout.addWidget(window.catalog_status)
    window.catalog_export.clicked.connect(lambda: export_catalog(window))
    window.catalog_table.currentCellChanged.connect(lambda *_: show_catalog_record(window))
    window.catalog_search.textChanged.connect(lambda _: refresh_catalog_panel(window))
    window.catalog_category.currentIndexChanged.connect(lambda _: refresh_catalog_panel(window))
    window.catalog_mode.currentIndexChanged.connect(lambda _: refresh_catalog_panel(window))
    window.tabs.addTab(page, "Каталог мира")


def refresh_catalog_panel(window):
    if not hasattr(window, "catalog_table"):
        return
    index = CatalogIndex(window._session)
    try:
        text = window.catalog_search.text().strip().casefold()
        category = window.catalog_category.currentData()
        rows = []
        if window.catalog_mode.currentIndex() == 1:
            for record in index.search(text, category, limit=50):
                d = record["definition"]
                rows.append((d["id"], d["name"], d["kind"]))
        else:
            for (id,) in index.db.execute(
                "SELECT id FROM catalog_instances WHERE quantity>0 ORDER BY id"
            ):
                record = index.lookup(id)
                if not record:
                    continue
                d, e = record["definition"], record["entity"]
                if category and category not in d["categories"]:
                    continue
                if text and text not in d["name"].casefold() and text not in id.casefold():
                    continue
                rows.append((id, d["name"], str(e["quantity"])))
                if len(rows) == 100:
                    break
        window.catalog_table.blockSignals(True)
        window.catalog_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                window.catalog_table.setItem(i, j, item)
        window.catalog_table.blockSignals(False)
        window.catalog_detail.clear()
        if window._session.catalog or (
            window._session.interactive_world
            and window._session.interactive_world.version == "interactive-world-3"
        ):
            path = window._saves.directory.parent / "world-catalog.sqlite3"
            try:
                index.publish(path)
            except (OSError, ValueError, sqlite3.Error) as error:
                window.catalog_status.setText("Рабочая SQLite-копия не обновлена: " + str(error))
            else:
                window.catalog_status.setText("Рабочая база: " + str(path))
        else:
            window.catalog_status.setText(
                "Стартовые типы доступны; постоянные новые записи появятся при генерации мастером."
            )
    finally:
        index.close()


def show_catalog_record(window):
    row = window.catalog_table.currentRow()
    if row < 0 or window.catalog_table.item(row, 0) is None:
        return
    index = CatalogIndex(window._session)
    try:
        record = index.lookup(window.catalog_table.item(row, 0).text())
        if record:
            window.catalog_detail.setPlainText(json.dumps(record, ensure_ascii=False, indent=2))
    finally:
        index.close()


def export_catalog(window):
    path, _ = QFileDialog.getSaveFileName(
        window, "Новый файл базы кампании", "campaign.sqlite3", "SQLite (*.sqlite3)"
    )
    if not path:
        return
    index = None
    try:
        index = CatalogIndex(window._session)
        index.export(path)
    except (OSError, ValueError) as error:
        window.catalog_detail.setPlainText("База не экспортирована: " + str(error))
    else:
        window.catalog_detail.setPlainText("Кампания и каталог экспортированы: " + path)
    finally:
        if index:
            index.close()
