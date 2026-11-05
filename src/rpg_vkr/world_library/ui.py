"""Optional standalone library browser, never opened during game/save loading."""

import json

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.world_library.model import read_jsonl


class LibraryWindow(QWidget):
    def __init__(self, library):
        super().__init__()
        self.setFont(QFont("Segoe UI", 10))
        self.library = library
        self.setWindowTitle("DND-NCFU — библиотека шаблонов мира")
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Название, описание или точный ID")
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
        self.card_preview = QTextEdit()
        self.card_preview.setReadOnly(True)
        tabs = QTabWidget()
        tabs.addTab(self.card_preview, "Карточка для мастера")
        tabs.addTab(self.details, "Все поля и происхождение")
        layout.addWidget(self.results, 1)
        layout.addWidget(tabs, 2)
        actions = QHBoxLayout()
        for label, callback in (
            ("Импорт JSONL", self.import_file),
            ("Предложить новый шаблон", self.propose_file),
            ("Создать экземпляр в копии мира", self.instantiate),
            ("Применить в копии мира", self.activate),
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
        self.card_preview.clear()

    def show_record(self, index):
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            from rpg_vkr.world_library.presentation import card, render

            revision = self.library.revision(row["id"])
            pinned = dict(
                self.library.execute(
                    "SELECT target_id,target_revision FROM wl_links WHERE id=? AND revision=?",
                    (row["id"], revision),
                ).fetchall()
            )
            resolve = lambda id: self.library.get(id, pinned[id])  # noqa: E731
            value = card(row, resolve=resolve, revision=revision)
            status = (
                "Справочная карточка; автоматического игрового действия нет."
                if value["mechanics"]["version"] == "descriptive"
                else "Программа: " + value["mechanics"]["version"]
            )
            pending = value["mechanics"]["pending_features"]
            if pending:
                status += f"\nОсобенностей без обработчика: {len(pending)}."
            self.card_preview.setPlainText(
                render(value)
                + "\n\n"
                + status
                + f"\nПроисхождение: {value['provenance']['origin']}"
                + f"\nID: {row['id']}; редакция: {revision}"
            )
            labels = {
                "mass_g": "Масса, г",
                "durability": "Прочность",
                "quality": "Качество",
                "purpose": "Назначение",
                "history": "История",
                "damage_count": "Кубиков урона",
                "damage_die": "Граней кубика",
                "penetration": "Пробитие",
                "hands": "Рук",
                "defence": "Защита",
                "slot": "Место экипировки",
                "compatible": "Совместимость",
                "hp_max": "Максимум HP",
                "level": "Уровень",
                "species": "Вид",
                "profession": "Профессия",
                "social_status": "Положение",
                "beliefs": "Убеждения",
                "appearance": "Внешность",
                "motivation": "Мотив",
                "biography": "Биография",
                "age_years": "Возраст",
                "surname": "Фамилия",
                "initial_mood": "Настроение",
                "mood_transitions": "Условия смены настроения",
                "territory": "Территория",
                "diet": "Питание",
                "tactics": "Поведение",
                "school": "Школа магии",
                "nature": "Природа",
                "mp": "Стоимость MP",
                "duration_turns": "Длительность, ходов",
                "components": "Компоненты формулы",
                "effect": "Предлагаемый эффект",
                "counterplay": "Противодействие",
                "proficiency": "Подготовка",
                "potency": "Сила",
                "fictional": "Вымышленное вещество",
                "nutrition": "Питательность",
                "shelf_days": "Срок хранения, дней",
                "habitat": "Место произрастания",
                "processing": "Обработка",
                "season": "Сезон",
                "harvest": "Сбор",
                "deposit": "Месторождение",
                "yield_percent": "Выход материала, %",
                "family": "Группа материала",
                "subject": "Тема",
                "author": "Автор",
                "objective": "Задача",
                "issuer": "Источник задания",
                "trigger": "Активация",
                "charges": "Заряды",
                "ability": "Характеристика",
                "use": "Применение",
                "limit": "Ограничение",
                "lifespan": "Срок жизни",
                "size": "Размер",
                "culture": "Культура",
                "trait": "Особенность",
                "minutes": "Время, минут",
                "difficulty": "Сложность",
                "labour_cp": "Стоимость работы, медных",
                "method": "Порядок работы",
                "mode": "Тип производства",
            }
            price = (
                "Цена: справочное значение не задано"
                if row["profile"] == "source_reference"
                else f"Цена: {row['price_cp']} медных"
            )
            lines = [row["name"], row["description"], "", price]
            for key, value in row["attributes"].items():
                if isinstance(value, dict):
                    value = "\n" + json.dumps(value, ensure_ascii=False, indent=2)
                if isinstance(value, list):
                    value = "; ".join(
                        f"{v['from']} → {v['to']}: {v['event']}"
                        if isinstance(v, dict) and {"from", "to", "event"} <= v.keys()
                        else f"{v['field']}: {v['value']}"
                        if isinstance(v, dict) and {"field", "value"} <= v.keys()
                        else str(v)
                        for v in value
                    )
                lines.append(f"{labels.get(key, key)}: {value}")
            if row["links"]:
                lines.extend(["", "Состав и связанные записи:"])
                for link in row["links"]:
                    target = resolve(link["target"])
                    lines.append(f"• {target['name']} × {link['quantity']} — {link['role']}")
            lines.extend(
                [
                    "",
                    "Запись без ручной редакторской приёмки.",
                    "Новые эффекты требуют обработчика движка.",
                    f"Происхождение: {row['provenance']['origin']}",
                    f"ID: {row['id']}",
                ]
            )
            if row["profile"] == "source_creature":
                lines.append("Справочные характеристики — из источника; внешний эскиз — авторский.")
            self.details.setPlainText("\n".join(lines))

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
        with_inventory = self.rows[index]["profile"] == "npc"
        try:
            record = preview(
                self.library,
                session,
                self.rows[index]["id"],
                instance_id,
                with_inventory=with_inventory,
            )
        except ValueError as error:
            if "pins a different template revision" not in str(error):
                raise
            answer = QMessageBox.question(
                self,
                "Новая редакция шаблона",
                "Создать новую редакцию для нового экземпляра?\n"
                "Уже существующие предметы и существа сохранят прежние свойства.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            record = preview(
                self.library,
                session,
                self.rows[index]["id"],
                instance_id,
                with_inventory=with_inventory,
                new_revision=True,
            )
        commit(session, record)
        export_session(session, destination)
        QMessageBox.information(
            self, "Создана копия мира", "Экземпляр размещён в текущей сцене. Исходный мир сохранён."
        )

    def activate(self):
        operation, ok = QInputDialog.getItem(
            self,
            "Действие движка",
            "Что применить?",
            ["Магическая формула", "Рецепт", "Еда лекарство яд книга или квестовая вещь"],
            0,
            False,
        )
        if not ok:
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "Мир с формулой у героя", "", "SQLite (*.sqlite3)"
        )
        if not source:
            return
        instance_id, ok = QInputDialog.getText(
            self, "Формула", "ID принадлежащего герою экземпляра:"
        )
        if not ok:
            return
        target_id = "hero"
        if operation != "Рецепт":
            target_id, ok = QInputDialog.getText(
                self, "Цель", "ID цели (hero — герой):", text="hero"
            )
            if not ok:
                return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Новая копия после применения", "", "SQLite (*.sqlite3)"
        )
        if not destination:
            return
        from rpg_vkr.storage.knowledge import export_session, restore_session

        session = restore_session(source)
        command = (
            "library_magic"
            if operation == "Магическая формула"
            else "library_recipe"
            if operation == "Рецепт"
            else "library_use"
        )
        session.perform_gameplay(
            command,
            {"item": instance_id, "target": target_id}
            if operation != "Рецепт"
            else {"item": instance_id},
            "library-magic-" + session._request_token(),
        )
        export_session(session, destination)
        QMessageBox.information(
            self, "Действие выполнено", "Создана новая копия с журналом действий движка."
        )
