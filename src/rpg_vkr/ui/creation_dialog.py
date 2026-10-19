"""Explicit homebrew creation with a fixed budget, separate from the legacy editor."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.application import Session
from rpg_vkr.domain.campaign import DESCRIPTION_LIMIT, WORLD_BRIEF_LIMIT, plain
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.progression import ARCHETYPES, POINT_BUDGET, validate_creation


class CreationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать героя · авторские правила")
        self.setMinimumSize(480, 550)
        self.resize(580, 740)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QFormLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        note = QLabel(
            "База 8, распределите 24 очка. Повышение на 1 стоит 1 очко; максимум 16. "
            "Это homebrew-профили, не полные классы SRD."
        )
        note.setWordWrap(True)
        layout.addRow(note)
        self.name_input = QLineEdit("Путник")
        self.name_input.setMaxLength(40)
        layout.addRow("Имя", self.name_input)
        self.class_choice = QComboBox()
        for key, archetype in ARCHETYPES.items():
            self.class_choice.addItem(archetype.name, key)
        layout.addRow("Класс / авторский профиль", self.class_choice)
        self.description_input = QPlainTextEdit()
        self.description_input.setAccessibleName("Свободное описание героя")
        self.description_input.setPlaceholderText(
            "Внешность, происхождение, семья, прошлое и желания героя. Можно оставить пустым."
        )
        self.description_input.setMaximumHeight(150)
        layout.addRow("Расскажите о герое", self.description_input)
        self.description_limit = QLabel(
            f"До {DESCRIPTION_LIMIT} символов. Исходный текст сохраняется без переписывания."
        )
        self.description_limit.setWordWrap(True)
        layout.addRow(self.description_limit)
        self.description_input.textChanged.connect(self._update_budget)
        self.world_brief_input = QPlainTextEdit()
        self.world_brief_input.setAccessibleName("Пожелания к миру и жанру")
        self.world_brief_input.setPlaceholderText(
            "Например: приключенческое фэнтези, редкая магия, торговля, интриги гильдий. "
            "Это пожелания к повествованию, а не выдача предметов или готовый мир."
        )
        self.world_brief_input.setMaximumHeight(100)
        layout.addRow("Мир, жанры и настроение", self.world_brief_input)
        self.world_brief_limit = QLabel(f"До {WORLD_BRIEF_LIMIT} символов. Поле необязательное.")
        self.world_brief_limit.setWordWrap(True)
        layout.addRow(self.world_brief_limit)
        self.world_brief_input.textChanged.connect(self._update_budget)
        self.generate_world = QCheckBox("Создать новый мир и сюжет мастером")
        self.generate_world.setChecked(not getattr(parent, "_legacy_controls", False))
        layout.addRow(self.generate_world)
        generation_note = QLabel(
            "Место и сюжет выбирает мастер по описаниям выше. Включите ИИ до "
            "создания героя; без подключения доступен автономный случайный "
            "старт."
        )
        generation_note.setWordWrap(True)
        layout.addRow(generation_note)
        self.kit_label = QLabel()
        self.kit_label.setWordWrap(True)
        layout.addRow(self.kit_label)
        self.scores = {}
        for ability, name in ABILITY_NAMES.items():
            spin = QSpinBox()
            spin.setRange(8, 16)
            self.scores[ability] = spin
            layout.addRow(name, spin)
            spin.valueChanged.connect(self._update_budget)
        recommended = QPushButton("Применить рекомендованные характеристики")
        recommended.clicked.connect(self.apply_recommended)
        layout.addRow(recommended)
        self.budget_label = QLabel()
        self.budget_label.setWordWrap(True)
        layout.addRow(self.budget_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Создать героя")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.class_choice.currentIndexChanged.connect(self._update_kit)
        self.name_input.textChanged.connect(self._update_budget)
        self.apply_recommended()
        self._update_kit()

    def apply_recommended(self) -> None:
        for ability, score in zip(
            ABILITY_NAMES, ARCHETYPES[self.class_choice.currentData()].scores, strict=True
        ):
            self.scores[ability].setValue(score)
        self._update_budget()

    def _update_kit(self) -> None:
        kit = ARCHETYPES[self.class_choice.currentData()]
        self.kit_label.setText(
            f"{kit.description}\nСтарт: {kit.gold} золотых, бинты ×{kit.bandages}, "
            f"{kit.equipment}, дорожный учебник. Здоровье 12/12."
        )

    def _update_budget(self) -> None:
        if not hasattr(self, "buttons"):
            return
        remaining = POINT_BUDGET - sum(spin.value() - 8 for spin in self.scores.values())
        self.budget_label.setText(f"Осталось очков: {remaining}. Для создания должно остаться 0.")
        used = len(self.description_input.toPlainText())
        world_used = len(self.world_brief_input.toPlainText())
        self.world_brief_limit.setText(
            f"Пожелания к миру: {world_used}/{WORLD_BRIEF_LIMIT} символов. "
            + ("Сократите текст." if world_used > WORLD_BRIEF_LIMIT else "Поле необязательное.")
        )
        self.description_limit.setText(
            f"Описание: {used}/{DESCRIPTION_LIMIT} символов. "
            + (
                "Лимит превышен; сократите текст. Он остаётся в поле ввода."
                if used > DESCRIPTION_LIMIT
                else "Исходный текст сохраняется без переписывания."
            )
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            remaining == 0
            and bool(self.name_input.text().strip())
            and len(self.description_input.toPlainText()) <= DESCRIPTION_LIMIT
            and world_used <= WORLD_BRIEF_LIMIT
        )

    def character(self) -> Character:
        character = Character(
            name=self.name_input.text().strip(),
            **{key: spin.value() for key, spin in self.scores.items()},
        )
        validate_creation(character, self.class_choice.currentData())
        return character

    def create_session(self) -> Session:
        description = plain(self.description_input.toPlainText(), DESCRIPTION_LIMIT, empty=True)
        return Session.create_hero(
            self.character(),
            self.class_choice.currentData(),
            description=description,
            world_brief=plain(self.world_brief_input.toPlainText(), WORLD_BRIEF_LIMIT, empty=True),
        )

    def accept(self) -> None:
        try:
            self.character()
            plain(self.description_input.toPlainText(), DESCRIPTION_LIMIT, empty=True)
            plain(self.world_brief_input.toPlainText(), WORLD_BRIEF_LIMIT, empty=True)
        except ValueError as error:
            QMessageBox.warning(self, "Проверьте героя", str(error))
            return
        super().accept()
