"""Searchable codex and accessible hover cards built solely from public knowledge."""

import json
from html import escape
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.ui.codex_icons import category_icon
from rpg_vkr.ui.knowledge import CATEGORIES, knowledge_entries


def card_html(entry, compact=False):
    fields = entry.fields[:3] if compact else entry.fields
    description = entry.description[:240] if compact else entry.description
    parts = [
        f"<h2>{escape(entry.title)}</h2>",
        f"<p><i>{escape(CATEGORIES[entry.category])} · "
        f"{'Частично известно' if entry.partial else 'Подтверждено'}</i></p>",
        "<p>" + escape(description).replace("\n", "<br>") + "</p>",
    ]
    for name, value in fields:
        value = value[:120] if compact else value
        parts.append(f"<p><b>{escape(name)}</b><br>{escape(value)}</p>")
    if not compact:
        for label, text in entry.notes:
            parts.append(f"<p><b>{escape(label)}</b><br>{escape(text)}</p>")
        parts.append(
            f"<p><i>Последнее наблюдение: ход {entry.last_seen}. "
            "Неизвестные сведения не раскрываются.</i></p>"
        )
    return (
        '<table width="320"><tr><td>' + "".join(parts) + "</td></tr></table>"
        if compact
        else "".join(parts)
    )


class EntryList(QListWidget):
    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            item = self.itemAt(event.pos())
            if item and item.data(Qt.ItemDataRole.UserRole):
                QToolTip.showText(
                    event.globalPos(),
                    card_html(item.data(Qt.ItemDataRole.UserRole), True),
                    self.viewport(),
                    self.visualItemRect(item),
                    6000,
                )
                return True
        return super().viewportEvent(event)


class ChroniclesPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.entries = ()
        self._token = None
        self._session = None
        layout = QVBoxLayout(self)
        eyebrow = QLabel("ЗНАНИЯ ВАШЕГО ГЕРОЯ")
        eyebrow.setProperty("eyebrow", True)
        layout.addWidget(eyebrow)
        heading = QLabel("Хроники мира")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        self.filters = QWidget()
        left = QVBoxLayout(self.filters)
        left.setContentsMargins(0, 8, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск в известных сведениях")
        self.search.setAccessibleName("Поиск в Хрониках мира")
        left.addWidget(self.search)
        self.categories = QListWidget()
        self.categories.setAccessibleName("Разделы Хроник мира")
        left.addWidget(self.categories, 1)
        self.state = QComboBox()
        self.state.addItems(["Все знания", "Рядом", "Содержит слухи", "Частично известно"])
        left.addWidget(self.state)
        self.sort = QComboBox()
        self.sort.addItems(["По названию", "Последние встречи"])
        left.addWidget(self.sort)
        self.splitter.addWidget(self.filters)
        self.list = EntryList()
        self.list.setAccessibleName("Известные объекты; стрелки — выбор, Enter — карточка")
        self.list.setSpacing(5)
        self.list.setWordWrap(True)
        self.splitter.addWidget(self.list)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setAccessibleName("Полная карточка знаний героя")
        self.detail.document().setDefaultFont(QFont("Segoe UI", 12))
        self.detail.document().setDefaultStyleSheet(
            "h2 {font-family: Georgia; font-size: 26px; margin-bottom: 12px;} "
            "p {margin-bottom: 12px; line-height: 140%;}"
        )
        for control in (self.list, self.categories, self.search, self.state, self.sort):
            control.setFont(QFont("Segoe UI", 11))
        self.splitter.addWidget(self.detail)
        self.splitter.setSizes([200, 290, 560])
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        export = QPushButton("Экспорт известных сведений…")
        export.clicked.connect(self.export)
        row.addWidget(export)
        layout.addLayout(row)
        self.categories.currentRowChanged.connect(lambda _: self.filter())
        self.search.textChanged.connect(lambda _: self.filter())
        self.state.currentIndexChanged.connect(lambda _: self.filter())
        self.sort.currentIndexChanged.connect(lambda _: self.filter())
        self.list.currentItemChanged.connect(lambda current, old: self.select(current))
        self.list.itemActivated.connect(lambda _: self.detail.setFocus())

    def resizeEvent(self, event):
        compact = self.width() < 850
        self.splitter.setOrientation(
            Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal
        )
        self.filters.setMaximumHeight(160 if compact else 16777215)
        self.list.setMaximumHeight(170 if compact else 16777215)
        if compact:
            self.splitter.setSizes([140, 140, 260])
        super().resizeEvent(event)

    def refresh(self):
        session = self.window._session
        token = (
            id(session),
            len(session.turns),
            id(session.world),
            id(session.catalog),
            id(session.interactive_world),
            id(session.chronicle),
            id(session.campaign),
        )
        if token == self._token:
            return
        self._token = token
        if self._session is not session:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.state.setCurrentIndex(0)
            self.detail.clear()
        self._session = session
        self.entries = knowledge_entries(session)
        category = self.categories.currentItem()
        chosen = category.data(Qt.ItemDataRole.UserRole) if category else ""
        self.categories.blockSignals(True)
        self.categories.clear()
        for key, title in (("", "Все записи"), *CATEGORIES.items()):
            count = sum(not key or e.category == key for e in self.entries)
            if not count and key:
                continue  # No empty demonstration sections.
            item = QListWidgetItem(category_icon(key), f"{title}  ·  {count}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.categories.addItem(item)
            if key == chosen:
                self.categories.setCurrentItem(item)
        if self.categories.currentRow() < 0:
            self.categories.setCurrentRow(0)
        self.categories.blockSignals(False)
        self.summary.setText(
            f"{session.character.name} · {session.current_place_name} · "
            "Только открытые сведения. Слухи отмечены отдельно."
        )
        self.filter()

    def filter(self):
        selected = self.list.currentItem()
        key = selected.data(Qt.ItemDataRole.UserRole).key if selected else ""
        category = self.categories.currentItem()
        category = category.data(Qt.ItemDataRole.UserRole) if category else ""
        text = self.search.text().strip().casefold()
        state = self.state.currentIndex()
        rows = [
            e
            for e in self.entries
            if (not category or e.category == category)
            and (not text or text in e.search_text)
            and (state != 1 or e.here)
            and (state != 2 or e.rumour)
            and (state != 3 or e.partial)
        ]
        rows.sort(
            key=(lambda e: (-e.last_seen, e.title.casefold()))
            if self.sort.currentIndex()
            else (lambda e: e.title.casefold())
        )
        self.list.blockSignals(True)
        self.list.clear()
        for entry in rows:
            item = QListWidgetItem(
                category_icon(entry.category),
                entry.title
                + "\n"
                + ("Слух · " if entry.rumour else "")
                + CATEGORIES[entry.category],
            )
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
            if entry.key == key:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentRow() < 0 and rows:
            self.list.setCurrentRow(0)
        self.select(self.list.currentItem())
        self.status.setText(f"Найдено записей: {len(rows)}. Наведите курсор для краткой карточки.")
        if not rows:
            self.detail.setPlainText(
                "Здесь пока нет известных сведений. Исследуйте мир или измените поиск."
            )

    def select(self, item):
        if item:
            parchment = self.window.theme_choice.currentText() != "Тёмная"
            self.detail.setStyleSheet(
                "QTextBrowser {background: #ede4ce; color: #27342f; "
                "border: 1px solid #b69c68; border-radius: 8px; padding: 22px;}"
                if parchment
                else "QTextBrowser {padding: 22px;}"
            )
            self.detail.setHtml(card_html(item.data(Qt.ItemDataRole.UserRole)))
        else:
            self.detail.clear()

    def open_entry(self, key):
        self.search.clear()
        self.categories.setCurrentRow(0)
        self.state.setCurrentIndex(0)
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole).key == key:
                self.list.setCurrentRow(row)
                self.detail.setFocus()
                break

    def export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Известные герою сведения", "chronicles.json", "JSON (*.json)"
        )
        if not path:
            return
        if Path(path).resolve().is_relative_to(self.window._saves.directory.resolve()):
            self.status.setText("Выберите файл вне папки игровых ячеек.")
            return
        campaign = self.window._session.campaign.world_id
        payload = {
            "format": "hero-knowledge-1",
            "entries": [e.public_dict(campaign) for e in self.entries],
        }
        try:
            with open(path, "x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
        except (OSError, ValueError):
            self.status.setText(
                "Экспорт не записан. Выберите новый файл; существующие данные не перезаписываются."
            )
        else:
            self.status.setText("Экспортированы только известные сведения героя.")
