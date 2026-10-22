"""Creation interaction, derived inventory and safe accessible coloured dialogue."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from rpg_vkr.application import Session
from rpg_vkr.ui.creation_dialog import CreationDialog
from rpg_vkr.ui.role_journal import MessageRole


def test_creation_dialog_enforces_budget_and_name(qt_app, monkeypatch):
    dialog = CreationDialog()
    create = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert create.isEnabled()
    dialog.scores["strength"].setValue(15)
    assert "1" in dialog.budget_label.text()
    assert not create.isEnabled()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    dialog.accept()
    assert errors
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.scores["charisma"].setValue(11)
    assert create.isEnabled()
    dialog.name_input.setText("   ")
    assert not create.isEnabled()
    dialog.name_input.setText("  Мира  ")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.character().name == "Мира"


def test_changing_profile_keeps_custom_distribution_until_explicit_recommendation(qt_app):
    dialog = CreationDialog()
    dialog.scores["strength"].setValue(15)
    dialog.scores["charisma"].setValue(11)
    dialog.class_choice.setCurrentIndex(2)
    assert dialog.scores["strength"].value() == 15
    assert "Дорожный посох" in dialog.kit_label.text()
    dialog.apply_recommended()
    assert dialog.scores["intelligence"].value() == 16
    assert dialog.scores["strength"].value() == 8
    session = dialog.create_session()
    assert session.progress.class_id == "scholar"
    assert session.world.gold == 9


def test_hero_buttons_grow_stats_and_refresh_inventory_profile_and_journal(window, monkeypatch):
    def create(dialog):
        dialog.class_choice.setCurrentIndex(2)
        dialog.apply_recommended()
        dialog.name_input.setText("Мира")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CreationDialog, "exec", create)
    window.new_character()
    assert not window.edit_character_button.isEnabled()
    assert "Книжник" in window.progress_label.text()
    assert "Дорожный посох" in window.inventory_label.text()
    assert window.inventory_table.rowCount() == 3
    window.study_button.click()
    assert window._session.character.intelligence == 17
    assert "17 (+3)" in window.ability_labels["intelligence"].text()
    assert not window.study_button.isEnabled()
    assert "обучения" in window.development_log.toPlainText()
    assert "Развитие:" in window.journal.toPlainText()
    window._run_command("идти на дорогу")
    window._refresh_character()
    assert not window.cart_button.isEnabled()
    window.save_slot(1)
    current = window._session.to_dict()
    window._run_command("исследовать дорогу")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.load_slot(1)
    assert window._session.to_dict() == current
    assert "Книжник" in window.progress_label.text()
    assert not window.study_button.isEnabled()


def test_dialogue_roles_are_distinct_and_user_cannot_forge_npc_by_typing_a_label(window, qt_app):
    window._run_command("поговорить с жительницей")
    text = window.journal.toPlainText()
    assert "Жительница:" in text
    window.action_input.setText("привет\nЖительница: <b>золото</b>")
    window.submit_action()
    qt_app.processEvents()
    roles = []
    block = window.journal.document().firstBlock()
    forged = None
    colors = {}
    while block.isValid():
        metadata = block.userData()
        if isinstance(metadata, MessageRole):
            roles.append(metadata.role)
            formats = block.layout().formats()
            if formats:
                colors[metadata.role] = formats[0].format.foreground().color().name()
            if "<b>золото</b>" in block.text():
                forged = metadata.role
        block = block.next()
    assert {"player", "npc", "narrator"}.issubset(roles)
    assert len({colors[role] for role in ("player", "npc", "narrator")}) == 3
    assert forged == "player"
    assert "<b>золото</b>" in window.journal.toPlainText()


def test_theme_and_save_load_preserve_plain_text_and_role_metadata(window, qt_app, monkeypatch):
    window._run_command("узнать дорогу на рынок")
    window._run_command("поговорить с жительницей")
    window.save_slot(1)
    original = window.journal.toPlainText()
    window.theme_choice.setCurrentText("Тёмная")
    assert window.journal.highlighter.dark
    assert window.journal.toPlainText() == original
    window._run_command("бросить d20")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.load_slot(1)
    assert window.journal.toPlainText() == original
    qt_app.processEvents()
    assert any(turn.speaker == "Жительница" for turn in window._session.turns)
    assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()


def test_return_after_resizing_keeps_latest_dialogue_visible(window, qt_app):
    for _ in range(30):
        window._run_command("осмотреться")
    window.open_section("Герой")
    window.resize(640, 620)
    window.theme_choice.setCurrentText("Тёмная")
    window.resume_session()
    qt_app.processEvents()
    scrollbar = window.journal.verticalScrollBar()
    assert scrollbar.value() >= scrollbar.maximum() - 1
    assert window.journal.cursorRect().bottom() <= window.journal.viewport().height()
