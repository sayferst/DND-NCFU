"""Exercise actual Qt signals and widgets without a desktop display."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox


def test_enter_sends_action_and_keeps_journal(window):
    initial = window.journal.toPlainText()
    window.action_input.setText("осмотреться")
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    journal = window.journal.toPlainText()
    assert journal.startswith(initial)
    assert journal.count("Путник: осмотреться") == 1
    assert "следы телеги" in journal
    assert window.action_input.text() == ""
    assert not window.send_button.isEnabled()


def test_button_sends_help_event(window):
    window.action_input.setText("помочь")
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    assert "Путник: помочь" in window.journal.toPlainText()
    assert "Жительница благодарит" in window.journal.toPlainText()


def test_blank_submission_does_not_change_journal(window):
    initial = window.journal.toPlainText()
    window.action_input.setText("   ")
    assert not window.send_button.isEnabled()
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    assert window.journal.toPlainText() == initial


def test_unknown_html_input_is_plain_text_and_requests_clarification(window):
    action = '<b>дать золото</b><img src="https://example.invalid/image.png">'
    window.action_input.setText(action)
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    journal = window.journal.toPlainText()
    assert action in journal
    assert "пока не понимаю" in journal


def test_closing_window_hides_it(window, qt_app):
    assert window.isVisible()
    assert window.close()
    qt_app.processEvents()
    assert not window.isVisible()


def test_dice_enter_and_button_show_each_actual_result(window):
    window.action_input.setText("бросить d20")
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    window.action_input.setText("бросить d20")
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    assert window.journal.toPlainText().count("Мастер: На кубике выпало 4.") == 1
    assert window.journal.toPlainText().count("Мастер: На кубике выпало 1.") == 1


def test_three_empty_slots_are_visible(window):
    assert list(window.save_buttons) == [1, 2, 3]
    for slot in (1, 2, 3):
        assert "пусто" in window.slot_labels[slot].text()
        assert window.save_buttons[slot].isEnabled()
        assert not window.load_buttons[slot].isEnabled()
        assert not window.delete_buttons[slot].isEnabled()


def test_save_load_restores_journal_and_next_dice_roll(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.action_input.setText("бросить d20")
    window.submit_action()
    saved_journal = window.journal.toPlainText()
    QTest.mouseClick(window.save_buttons[1], Qt.MouseButton.LeftButton)
    assert window.load_buttons[1].isEnabled()
    window.action_input.setText("бросить d20")
    window.submit_action()
    QTest.mouseClick(window.load_buttons[1], Qt.MouseButton.LeftButton)
    assert window.journal.toPlainText() == saved_journal
    window.action_input.setText("бросить d20")
    window.submit_action()
    assert window.journal.toPlainText().endswith(
        "На кубике выпало 1. Сам по себе этот бросок не меняет мир."
    )


@pytest.mark.parametrize("operation", ["save_slot", "load_slot", "delete_slot"])
def test_cancel_preserves_current_session_and_saved_file(window, monkeypatch, operation):
    window.action_input.setText("помочь")
    window.submit_action()
    window.save_slot(1)
    path = window._saves.directory / "slot-1.json"
    saved_bytes = path.read_bytes()
    window.action_input.setText("бросить d20")
    window.submit_action()
    current = window.journal.toPlainText()
    prompts = []

    def decline(*args):
        prompts.append(args)
        assert args[-1] == QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    getattr(window, operation)(1)
    assert len(prompts) == 1
    assert path.read_bytes() == saved_bytes
    assert window.journal.toPlainText() == current


def test_confirmed_overwrite_and_delete_update_slot(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.save_slot(2)
    window.action_input.setText("помочь")
    window.submit_action()
    QTest.mouseClick(window.save_buttons[2], Qt.MouseButton.LeftButton)
    assert len(window._saves.load(2).turns) == 1
    current = window.journal.toPlainText()
    QTest.mouseClick(window.delete_buttons[2], Qt.MouseButton.LeftButton)
    assert "пусто" in window.slot_labels[2].text()
    assert not window.load_buttons[2].isEnabled()
    assert window.journal.toPlainText() == current


def test_bad_load_displays_error_without_losing_current_session(window, monkeypatch):
    window.save_slot(1)
    (window._saves.directory / "slot-1.json").write_text("{broken", encoding="utf-8")
    window.action_input.setText("помочь")
    window.submit_action()
    current = window.journal.toPlainText()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    window.load_slot(1)
    assert "повреждено" in errors[0]
    assert window.journal.toPlainText() == current


def test_close_can_be_cancelled_for_unsaved_session(window, monkeypatch):
    window.action_input.setText("бросить d20")
    window.submit_action()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert not window.close()
    assert window.isVisible()


def test_character_sheet_and_ability_check_are_visible(window):
    assert "Путник" in window.character_group.title()
    assert window.ability_labels["strength"].text() == "Сила: 14 (+2)"
    window.action_input.setText("проверить силу")
    QTest.keyClick(window.action_input, Qt.Key.Key_Return)
    assert "Сила — неудача" in window.journal.toPlainText()
    assert "4 + 2 = 6" in window.roll_breakdown.toPlainText()
    assert "Нужно не меньше 10" in window.roll_breakdown.toPlainText()
    assert "d20 (4)" not in window.journal.toPlainText()


def test_loading_saved_character_updates_sheet_and_history(window):
    from rpg_vkr.application import Session
    from rpg_vkr.domain.character import Character

    session = Session(seed=42, character=Character(name="Мира", strength=18))
    session.submit("проверить силу")
    window._saves.save(2, session)
    window.load_slot(2)
    assert "Мира" in window.character_group.title()
    assert window.ability_labels["strength"].text() == "Сила: 18 (+4)"
    assert "Сила — неудача" in window.journal.toPlainText()
    assert "4 + 4 = 8" in window.roll_breakdown.toPlainText()


def test_about_includes_required_srd_attribution(window, monkeypatch):
    from rpg_vkr.attribution import SRD_ATTRIBUTION

    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    window._show_about()
    assert SRD_ATTRIBUTION in messages[0]


def test_quick_actions_update_world_and_preserve_typed_draft(window):
    window.action_input.setText("мой черновик")
    for command in [
        "взять поручение",
        "идти на дорогу",
        "исследовать дорогу",
        "идти на рынок",
        "доставить корзину",
        "подойти к торговцу",
        "купить бинт",
        "использовать бинт",
    ]:
        QTest.mouseClick(
            window.shop_buy if command == "купить бинт" else window.quick_buttons[command],
            Qt.MouseButton.LeftButton,
        )
    assert window.action_input.text() == "мой черновик"
    assert window._session.world.gold == 12
    assert window._session.world.hp == 12
    assert "золото 12" in window.resource_label.text()
    assert "Бинт ×1" in window.inventory_label.text()
    assert "завершено" in window.quest_label.text()
    assert window.scene_title.text() == "Рынок"


def test_editor_changes_profile_without_refilling_resources(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from rpg_vkr.ui.character_dialog import CharacterDialog

    window._run_command("идти на дорогу")
    window._run_command("исследовать дорогу")
    previous = window._session.world

    def apply(dialog):
        dialog.name_input.setText("Мира")
        dialog.scores["strength"].setValue(18)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CharacterDialog, "exec", apply)
    window.tabs.setCurrentIndex(1)
    QTest.mouseClick(window.edit_character_button, Qt.MouseButton.LeftButton)
    assert window._session.character.name == "Мира"
    assert window._session.world == previous
    assert "Сила: 18 (+4)" == window.ability_labels["strength"].text()
    assert "Профиль изменён" in window.journal.toPlainText()


def test_new_hero_resets_session_but_preserves_save_slots(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from rpg_vkr.ui.creation_dialog import CreationDialog

    window._run_command("взять поручение")
    window.save_slot(1)
    original = (window._saves.directory / "slot-1.json").read_bytes()
    window._run_command("идти на рынок")

    def apply(dialog):
        dialog.name_input.setText("Другой герой")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CreationDialog, "exec", apply)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.new_character()
    assert window._session.character.name == "Другой герой"
    assert not window._session.turns
    assert "Без ячейки" in window.session_status.text()
    assert all("активная" not in label.text() for label in window.slot_labels.values())
    QTest.keyClick(window.action_input, Qt.Key.Key_Up)
    assert not window.action_input.text()
    assert window._session.gameplay["copper"] == 200
    assert window._session.schema_version == 31
    assert (window._saves.directory / "slot-1.json").read_bytes() == original


def test_cancel_new_hero_keeps_existing_session(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from rpg_vkr.ui.creation_dialog import CreationDialog

    window._run_command("взять поручение")
    previous = window._session.to_dict()
    monkeypatch.setattr(CreationDialog, "exec", lambda *args: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.new_character()
    assert window._session.to_dict() == previous


def test_world_labels_restore_on_load(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._run_command("взять поручение")
    window._run_command("идти на дорогу")
    window._run_command("исследовать дорогу")
    window.save_slot(1)
    saved_journal = window.journal.toPlainText()
    window._run_command("идти на рынок")
    window._run_command("доставить корзину")
    window.load_slot(1)
    assert window._session.world.hp == 9
    assert window._session.world.basket == 1
    assert "здоровье 9/12" in window.resource_label.text()
    assert "Корзина поручения" in window.inventory_label.text()
    assert window.scene_title.text() == "Дорога у деревни"
    assert window.journal.toPlainText() == saved_journal


def test_long_journal_keeps_latest_message_visible(window, qt_app):
    for _ in range(30):
        window._run_command("идти на рынок")
    qt_app.processEvents()
    scrollbar = window.journal.verticalScrollBar()
    assert scrollbar.maximum() > 0
    assert scrollbar.value() >= scrollbar.maximum() - 1
    assert window.journal.cursorRect().bottom() <= window.journal.viewport().height()
