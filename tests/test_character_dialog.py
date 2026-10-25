"""Actual editor validation and explicit acceptance/cancellation."""

from PySide6.QtWidgets import QDialog, QMessageBox

from rpg_vkr.domain.character import Character
from rpg_vkr.ui.character_dialog import CharacterDialog


def test_editor_applies_name_and_several_abilities(qt_app):
    dialog = CharacterDialog(Character())
    dialog.name_input.setText("  Мира  ")
    dialog.scores["strength"].setValue(18)
    dialog.scores["charisma"].setValue(16)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.character() == Character(name="Мира", strength=18, charisma=16)


def test_editor_rejects_blank_name_without_accepting(qt_app, monkeypatch):
    dialog = CharacterDialog(Character())
    dialog.name_input.setText("   ")
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert messages


def test_cancel_does_not_change_original_character(qt_app):
    original = Character()
    dialog = CharacterDialog(original)
    dialog.name_input.setText("Новое имя")
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert original.name == "Путник"
