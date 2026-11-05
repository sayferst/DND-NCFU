"""Optional standalone library browser, never opened during game/save loading."""

import json

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.world_library.model import read_jsonl


class LibraryWindow(QWidget):
    def __init__(self, library):
        super().__init__()
        self.library = library
        self.setWindowTitle("DND-NCFU — библиотека шаблонов мира")
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Название или описание")
        self.category = QComboBox()
        self.category.addItem("Все категории", "")
        for (category,) in library.execute("SELECT id FROM wl_categories ORDER BY id").fetchall():
            self.category.addItem(category, category)
        search = QPushButton("Найти")
        filters.addWidget(self.query)
        filters.addWidget(self.category)
        filters.addWidget(search)
        layout.addLayout(filters)
        self.results = QListWidget()
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.details, 2)
        actions = QHBoxLayout()
        for label, callback in (
            ("Импорт JSONL", self.import_file),
            ("Предложить новый шаблон", self.propose_file),
            ("Создать экземпляр в копии мира", self.instantiate),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=callback: self.guarded(fn))
            actions.addWidget(button)
        layout.addLayout(actions)
        search.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.category.currentIndexChanged.connect(self.search)
        self.results.currentRowChanged.connect(self.show_record)
        self.rows = []
        self.search()

    def guarded(self, callback):
        try:
            callback()
        except (ValueError, KeyError, OSError) as exc:
            QMessageBox.warning(self, "Операция отклонена", str(exc))

    def search(self):
        self.rows = self.library.search(self.query.text(), self.category.currentData(), 100)
        self.results.clear()
        self.results.addItems([f"{r['name']} · {r['id']}" for r in self.rows])
        self.details.clear()

    def show_record(self, index):
        if 0 <= index < len(self.rows):
            self.details.setPlainText(json.dumps(self.rows[index], ensure_ascii=False, indent=2))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт шаблонов", "", "JSONL (*.jsonl)")
        if path:
            count = self.library.import_records(read_jsonl(path), actor="local-library-ui")
            self.search()
            QMessageBox.information(self, "Импорт завершён", f"Проверено записей: {count}")

    def propose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Один новый шаблон", "", "JSON (*.json)")
        if not path:
            return
        from pathlib import Path

        row = json.loads(Path(path).read_text(encoding="utf-8"))
        proposal = self.library.propose(row, model="local-ui", prompt_version="manual-1")
        answer = QMessageBox.question(
            self,
            "Проверить предложение",
            "Схема и ссылки проверены. Добавить этот шаблон в библиотеку?\n"
            "Это не выдаёт предметы герою и не включает новые игровые эффекты.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.library.approve(proposal, actor="local-maintainer")
            self.search()

    def instantiate(self):
        index = self.results.currentRow()
        if not 0 <= index < len(self.rows):
            raise ValueError("Выберите шаблон")
        source, _ = QFileDialog.getOpenFileName(
            self, "Экспорт мира SQLite", "", "SQLite (*.sqlite3)"
        )
        if not source:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Новая копия мира", "", "SQLite (*.sqlite3)"
        )
        if not destination:
            return
        instance_id, ok = QInputDialog.getText(
            self, "ID экземпляра", "Устойчивый ID (латиница, цифры, _):"
        )
        if not ok:
            return
        from rpg_vkr.storage.knowledge import export_session, restore_session
        from rpg_vkr.world_library.bridge import commit, preview

        session = restore_session(source)
        record = preview(self.library, session, self.rows[index]["id"], instance_id)
        commit(session, record)
        export_session(session, destination)
        QMessageBox.information(
            self, "Создана копия мира", "Экземпляр размещён в текущей сцене. Исходный мир сохранён."
        )
