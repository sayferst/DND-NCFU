"""Searchable codex and accessible hover cards built solely from public knowledge."""

import json
from html import escape
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTabBar,
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
        heading = QLabel("Энциклопедия мира")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.category_tabs = QTabBar()
        self.category_tabs.setObjectName("sectionTabs")
        self.category_tabs.setExpanding(False)
        self.category_tabs.setUsesScrollButtons(True)
        self.category_tabs.setAccessibleName("Категории энциклопедии")
        layout.addWidget(self.category_tabs)
        self.filters = QWidget()
        left = QVBoxLayout(self.filters)
        left.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filters)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск в известных сведениях")
        self.search.setAccessibleName("Поиск в Хрониках мира")
        left.addWidget(self.search)
        self.categories = QListWidget()
        self.categories.setAccessibleName("Разделы Хроник мира")
        self.categories.hide()
        self.compact_categories = QComboBox()
        self.compact_categories.setAccessibleName("Разделы Хроник мира в небольшом окне")
        self.compact_categories.hide()
        self.refinements = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        left.addLayout(self.refinements)
        self.state = QComboBox()
        self.state.addItems(["Все знания", "Рядом", "Содержит слухи", "Частично известно"])
        self.refinements.addWidget(self.state)
        self.sort = QComboBox()
        self.sort.addItems(["По названию", "Последние встречи"])
        self.refinements.addWidget(self.sort)
        self.list = EntryList()
        self.list.setAccessibleName("Известные объекты; стрелки — выбор, Enter — карточка")
        self.list.setSpacing(5)
        self.list.setWordWrap(True)
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setGridSize(QSize(205, 205))
        self.list.setIconSize(QSize(180, 125))
        self.list.setUniformItemSizes(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        layout.addWidget(self.stack, 1)
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
        self.stack.addWidget(self.detail)
        self.back_button = QPushButton("← Вернуться к записям")
        self.back_button.clicked.connect(self.back)
        layout.addWidget(self.back_button)
        self.back_button.hide()
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.expand_card = QPushButton("Открыть карточку")
        self.expand_card.clicked.connect(self.open_card)
        row.addWidget(self.expand_card)
        self.describe_button = QPushButton("Уточнить описание")
        self.describe_button.setToolTip("Подготовить вопрос мастеру без отправки и расходов")
        self.describe_button.clicked.connect(self.describe_object)
        row.addWidget(self.describe_button)
        self.export_button = QPushButton("Экспорт известных сведений…")
        self.export_button.clicked.connect(self.export)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.categories.currentRowChanged.connect(lambda _: self.filter())
        self.category_tabs.currentChanged.connect(self.categories.setCurrentRow)
        self.list.itemClicked.connect(lambda _: self.open_card())
        self.compact_categories.currentIndexChanged.connect(self.categories.setCurrentRow)
        self.search.textChanged.connect(lambda _: self.filter())
        self.state.currentIndexChanged.connect(lambda _: self.filter())
        self.sort.currentIndexChanged.connect(lambda _: self.filter())
        self.list.currentItemChanged.connect(lambda current, old: self.select(current))
        self.list.itemActivated.connect(lambda _: self.open_card())

    def open_card(self):
        if not self.list.currentItem():
            return
        self.stack.setCurrentIndex(1)
        self.back_button.show()
        self.expand_card.hide()
        self.detail.setFocus()
        if hasattr(self.window, "motion"):
            self.window.motion.reveal(self.detail)

    def back(self):
        self.stack.setCurrentIndex(0)
        self.back_button.hide()
        self.expand_card.show()
        self.list.setFocus()
        if hasattr(self.window, "motion"):
            self.window.motion.reveal(self.list)

    def describe_object(self):
        item = self.list.currentItem()
        if not item:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry.category != "items":
            return
        if self.window.action_input.text().strip():
            self.status.setText("В поле действия уже есть текст. Сохраните или отправьте его.")
            return
        self.window.action_input.setText(
            f"Мастер, подробно опиши предмет «{entry.title}»: его конкретный тип, "
            "внешний вид и известное назначение. Сохрани описание в Хрониках. "
            "Используй уже известные признаки, не раскрывай неизученные свойства."
        )
        self.window.open_section("Приключение")
        self.window.action_input.setFocus()
        self.window.statusBar().showMessage(
            "Вопрос подготовлен. Нажмите «Отправить» для обращения к мастеру."
        )

    def resizeEvent(self, event):
        compact = self.width() < 850
        if hasattr(self, "image_controls"):
            self.image_controls.setVisible(not compact)
            self.image_menu_button.setVisible(compact)
        self.export_button.setText("Экспорт…" if compact else "Экспорт известных сведений…")
        self.status.setVisible(not compact)
        self.list.setGridSize(QSize(180 if compact else 220, 205))
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
            self.back()
        self._session = session
        self.entries = (
            knowledge_entries(session)
            if session.generated_world or self.window._legacy_controls
            else ()
        )
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
        self.category_tabs.blockSignals(True)
        while self.category_tabs.count():
            self.category_tabs.removeTab(0)
        for index in range(self.categories.count()):
            self.category_tabs.addTab(self.categories.item(index).text())
        self.category_tabs.setCurrentIndex(self.categories.currentRow())
        self.category_tabs.blockSignals(False)
        self.compact_categories.blockSignals(True)
        self.compact_categories.clear()
        for index in range(self.categories.count()):
            item = self.categories.item(index)
            self.compact_categories.addItem(item.icon(), item.text())
        self.compact_categories.setCurrentIndex(self.categories.currentRow())
        self.compact_categories.blockSignals(False)
        self.summary.setText(
            f"{session.character.name} · {session.current_place_name} · "
            "Только открытые сведения. Слухи отмечены отдельно."
        )
        self.filter()

    def filter(self):
        self.category_tabs.blockSignals(True)
        self.category_tabs.setCurrentIndex(self.categories.currentRow())
        self.category_tabs.blockSignals(False)
        self.compact_categories.blockSignals(True)
        self.compact_categories.setCurrentIndex(self.categories.currentRow())
        self.compact_categories.blockSignals(False)
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
                self.thumbnail(entry),
                entry.title
                + "\n"
                + ("Слух · " if entry.rumour else "")
                + CATEGORIES[entry.category],
            )
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setSizeHint(QSize(200, 195))
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

    def thumbnail(self, entry):
        from rpg_vkr.storage.campaigns import CampaignRepository

        if hasattr(self.window, "visuals"):
            registry = self.window.visuals.registry
            asset = registry.latest_for(
                CampaignRepository.identity(self.window._session), entry.key
            )
            if asset:
                try:
                    image = QPixmap(str(registry.asset_path(asset)))
                    return QIcon(
                        image.scaled(
                            180,
                            125,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                except (OSError, ValueError):
                    pass
        return category_icon(entry.category)

    def select(self, item):
        self.describe_button.setVisible(
            bool(item and item.data(Qt.ItemDataRole.UserRole).category == "items")
        )
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
                self.open_card()
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
