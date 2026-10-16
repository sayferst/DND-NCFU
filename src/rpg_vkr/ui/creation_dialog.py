"""Explicit homebrew creation with a fixed budget, separate from the legacy editor."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.progression import ARCHETYPES, POINT_BUDGET, validate_creation


class CreationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать героя · авторские правила")
        self.setMinimumWidth(430)
        layout = QFormLayout(self)
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
        layout.addRow("Профиль", self.class_choice)
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
        layout.addRow(self.buttons)
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
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            remaining == 0 and bool(self.name_input.text().strip())
        )

    def character(self) -> Character:
        character = Character(
            name=self.name_input.text().strip(),
            **{key: spin.value() for key, spin in self.scores.items()},
        )
        validate_creation(character, self.class_choice.currentData())
        return character

    def create_session(self) -> Session:
        return Session.create_hero(self.character(), self.class_choice.currentData())

    def accept(self) -> None:
        try:
            self.character()
        except ValueError as error:
            QMessageBox.warning(self, "Проверьте героя", str(error))
            return
        super().accept()
