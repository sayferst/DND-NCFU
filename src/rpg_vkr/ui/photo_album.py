"""Campaign-scoped public captions over the original immutable visual registry."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.ui.knowledge import knowledge_entries

CATEGORIES = (
    ("", "Все"),
    ("people", "Персонажи"),
    ("creatures", "Существа"),
    ("items", "Предметы"),
    ("places", "Локации"),
    ("events", "События"),
)


class PhotoAlbum(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window, self.campaign = window, None
        self.rows = []
        layout = QVBoxLayout(self)
        title = QLabel("Фотоальбом приключения")
        title.setProperty("heading", True)
        layout.addWidget(title)
        self.categories = QTabBar()
        self.categories.setObjectName("sectionTabs")
        self.categories.setExpanding(False)
        self.categories.setUsesScrollButtons(True)
        for _, name in CATEGORIES:
            self.categories.addTab(name)
        layout.addWidget(self.categories)
        self.history = QCheckBox("Показать прошлые версии")
        layout.addWidget(self.history)
        self.empty = QLabel("Ваша история только начинается. Первые иллюстрации сохранятся здесь.")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.list = QListWidget()
        self.list.setObjectName("albumCards")
        self.list.setAccessibleName("Иллюстрации текущего приключения")
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setGridSize(QSize(230, 230))
        self.list.setIconSize(QSize(210, 160))
        self.list.setWordWrap(True)
        self.list.setSpacing(8)
        layout.addWidget(self.list, 1)
        self.open_button = QPushButton("Открыть фотографию")
        self.open_button.clicked.connect(self.open_photo)
        layout.addWidget(self.open_button)
        back = QPushButton("В энциклопедию мира")
        back.clicked.connect(lambda: window.open_section("Энциклопедия мира"))
        layout.addWidget(back)
        self.categories.currentChanged.connect(lambda _: self.refresh())
        self.history.toggled.connect(lambda _: self.refresh())
        self.list.itemClicked.connect(lambda _: self.open_photo())
        self.list.itemActivated.connect(lambda _: self.open_photo())

    def refresh(self):
        controller = getattr(self.window, "visuals", None)
        session = self.window._session
        campaign = CampaignRepository.identity(session)
        previous = self.list.currentItem()
        selected = previous.data(Qt.ItemDataRole.UserRole)["id"] if previous else ""
        self.list.clear()
        if self.campaign != campaign:
            self.campaign = campaign
            selected = ""
        entries = {e.key: e for e in knowledge_entries(session)} if session.generated_world else {}
        rows = (
            controller.registry.campaign_assets(campaign, history=self.history.isChecked())
            if controller
            else []
        )
        self.rows = []
        category = CATEGORIES[max(0, self.categories.currentIndex())][0]
        for asset in rows:
            entry = entries.get(asset.get("entity") or asset["subject"].removeprefix("entity:"))
            title = asset.get("title") or (entry.title if entry else "Иллюстрация приключения")
            group = asset.get("category") or (entry.category if entry else "events")
            row = asset | {
                "title": title,
                "category": group,
                "description": asset.get("description")
                or (entry.description if entry else asset["created"]),
                "entry": entry.key if entry else "",
            }
            if category and category != group:
                continue
            self.rows.append(row)
            item = QListWidgetItem(title + f"\nВерсия {row['version']} · {row['created'][:10]}")
            item.setSizeHint(QSize(220, 220))
            item.setToolTip(row["description"][:300])
            item.setData(Qt.ItemDataRole.UserRole, row)
            try:
                image = QPixmap(str(controller.registry.asset_path(row)))
                item.setIcon(
                    QIcon(
                        image.scaled(
                            210,
                            160,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                )
            except (OSError, ValueError):
                item.setText(title + "\nФайл недоступен")
            self.list.addItem(item)
            if row["id"] == selected:
                self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.empty.setVisible(not self.rows)
        self.open_button.setEnabled(bool(self.rows))

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)

    def open_photo(self):
        item = self.list.currentItem()
        if not item:
            return
        campaign = self.campaign
        rows = list(self.rows)
        index = [r["id"] for r in rows].index(item.data(Qt.ItemDataRole.UserRole)["id"])
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Фотоальбом · воспоминание")
        dialog.resize(900, 750)
        layout = QVBoxLayout(dialog)
        title, image, description = QLabel(), QLabel(), QLabel()
        title.setProperty("heading", True)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        for label in (title, description):
            label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)
        layout.addWidget(image, 1)
        layout.addWidget(description)
        actions = QHBoxLayout()
        previous, following = QPushButton("← Назад"), QPushButton("Вперёд →")
        source = QPushButton("Открыть запись")
        close = QPushButton("Закрыть")
        for button in (previous, following, source, close):
            actions.addWidget(button)
        layout.addLayout(actions)

        def show(step=0):
            nonlocal index
            if CampaignRepository.identity(self.window._session) != campaign:
                dialog.reject()
                return
            index = (index + step) % len(rows)
            row = rows[index]
            title.setText(row["title"])
            description.setText(row["description"][:1500])
            try:
                pixmap = QPixmap(str(self.window.visuals.registry.asset_path(row)))
                image.setPixmap(
                    pixmap.scaled(
                        820,
                        450,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            except (ValueError, OSError):
                image.setText("Изображение недоступно. Сохранённая история остаётся в альбоме.")
            previous.setEnabled(len(rows) > 1)
            following.setEnabled(len(rows) > 1)

        def open_source():
            if CampaignRepository.identity(self.window._session) != campaign:
                dialog.reject()
                return
            row = rows[index]
            dialog.accept()
            if row["entry"]:
                self.window.open_section("Энциклопедия мира")
                self.window.chronicles_panel.open_entry(row["entry"])
            else:
                self.window.open_section("Приключение")

        previous.clicked.connect(lambda: show(-1))
        following.clicked.connect(lambda: show(1))
        source.clicked.connect(open_source)
        close.clicked.connect(dialog.accept)
        show()
        dialog.exec()
