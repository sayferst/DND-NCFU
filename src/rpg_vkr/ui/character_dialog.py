"""Explicit sandbox profile editing; resources cannot be edited here."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
)

from rpg_vkr.domain.character import ABILITY_NAMES, Character


class CharacterDialog(QDialog):
    def __init__(self, character: Character, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Профиль героя · песочница")
        layout = QFormLayout(self)
        note = QLabel(
            "Свободная настройка для прототипа. Это не полный генератор персонажа по SRD."
        )
        note.setWordWrap(True)
        layout.addRow(note)
        self.name_input = QLineEdit(character.name)
        self.name_input.setMaxLength(40)
        layout.addRow("Имя", self.name_input)
        self.scores: dict[str, QSpinBox] = {}
        for ability, label in ABILITY_NAMES.items():
            spin = QSpinBox()
            spin.setRange(1, 30)
            spin.setValue(character.score(ability))
            self.scores[ability] = spin
            layout.addRow(label, spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def character(self) -> Character:
        return Character(
            name=self.name_input.text().strip(),
            **{ability: spin.value() for ability, spin in self.scores.items()},
        )

    def accept(self) -> None:
        try:
            self.character()
        except ValueError:
            QMessageBox.warning(
                self, "Проверьте имя", "Введите непустое имя героя (до 40 символов)."
            )
            return
        super().accept()
