"""The story and the persistent audit panel share the same saved result."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from rpg_vkr.application import Session


def test_panel_remains_visible_across_sections_and_on_small_screen(window, qt_app):
    for section in ("Приключение", "Схватка", "Сохранения", "Карта", "Главное меню"):
        window.open_section(section)
        qt_app.processEvents()
        assert window.resolution_panel.isVisible()
        assert window.roll_breakdown.isVisible()
    window.open_section("Приключение")
    window.resize(640, 620)
    window.font_size.setValue(20)
    qt_app.processEvents()
    assert window.width() == 640
    assert window.height() == 620
    assert window.journal.height() >= 160
    assert window.roll_breakdown.width() >= 170
    assert window.roll_breakdown.height() >= 100
    assert window.action_input.isVisible()
    assert window.send_button.isVisible()
    assert window.resolution_panel.geometry().right() < window.width()


def test_draft_guidance_and_history_view_never_change_state_or_dice(window):
    before = window._session.to_dict()
    window.action_input.setText("атаковать стражника")
    assert "сделает цель враждебной" in window.action_guidance.text()
    assert window._session.to_dict() == before
    window.action_input.setText("атаковать волка")
    assert "Цели здесь нет" in window.action_guidance.text()
    window._run_command("бросить кубик")
    window._run_command("проверить харизму")
    before = window._session.to_dict()
    checkpoint = window._session.dice.checkpoint()
    window.breakdown_selector.setCurrentIndex(0)
    assert "Кубик с 20 гранями: 4" in window.roll_breakdown.toPlainText()
    assert "Проверки успеха и урона не было" in window.roll_breakdown.toPlainText()
    window.breakdown_selector.setCurrentIndex(1)
    assert "1 − 1 = 0" in window.roll_breakdown.toPlainText()
    assert window._session.to_dict() == before
    assert window._session.dice.checkpoint() == checkpoint


def test_non_roll_action_keeps_previous_breakdown_clearly_labelled(window):
    window._run_command("проверить силу")
    calculation = window.roll_breakdown.toPlainText()
    window._run_command("осмотреться")
    assert window.action_result.text().startswith("Без броска\nосмотреться")
    assert window.roll_breakdown.toPlainText() == calculation
    assert "Действие №1: проверить силу" in calculation
    assert "Ворота деревни" not in calculation


def test_genuine_v6_load_preserves_file_and_rng_but_changes_only_display(window, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "save-v6.json"
    content = fixture.read_bytes()
    window._saves.directory.mkdir(parents=True)
    path = window._saves.directory / "slot-1.json"
    path.write_bytes(content)
    window.load_slot(1)
    assert path.read_bytes() == content
    assert "d20" in window._session.turns[-1].text
    assert "d20" not in window.journal.toPlainText()
    assert "20 + 1 = 21" in window.roll_breakdown.toPlainText()
    assert window._session.combat.surprise
    window._run_command("атаковать волка")
    journal = window.journal.toPlainText()
    assert "Скрытая атака ×2 · урон 16" in journal
    assert "=" not in journal
    assert "(6 + 2) × 2 = 16" in window.roll_breakdown.toPlainText()
    assert "9 + 3 = 12" in window.roll_breakdown.toPlainText()
    assert "Развитие:" in journal
    assert window._session.progress.level == 2
    assert window._session.combat.actor("wolf").hp == 0
    assert "ответ противника" not in window.roll_breakdown.toPlainText()
    window.save_slot(2)
    saved = window._session.to_dict()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.load_slot(2)
    assert window._session.to_dict() == saved
    assert window.journal.toPlainText() == journal
    assert window._session.submit("бросить кубик").roll.value == 17
    assert path.read_bytes() == content


def test_style_changes_apply_to_both_views_without_mutation(window):
    window._run_command("проверить силу")
    before = window._session.to_dict()
    window.theme_choice.setCurrentText("Тёмная")
    window.font_size.setValue(17)
    window.bold_text.setChecked(False)
    assert window.roll_breakdown.font().pointSize() == 17
    assert window.action_result.font().pointSize() == 17
    assert not window.roll_breakdown.font().bold()
    assert window._session.to_dict() == before


def test_new_session_drops_old_breakdown_selection(window):
    window._run_command("бросить кубик")
    assert window.breakdown_selector.count() == 1
    window._session = Session(seed=10)
    window._refresh_character()
    window._render_journal()
    assert window.breakdown_selector.count() == 0
    assert "Бросков пока нет" in window.roll_breakdown.toPlainText()
    assert window.action_result.text() == "Пока нет действий."


@pytest.mark.parametrize(
    "question", ["что я вижу?", "что вокруг?", "где я нахожусь?", "где мы находимся?"]
)
def test_world_questions_during_encounter_are_read_only(window, question):
    window._run_command("идти на дорогу")
    window._run_command("подкрасться к волку")
    before_world = window._session.world
    before_combat = window._session.combat
    checkpoint = window._session.dice.checkpoint()
    window._run_command(question)
    reply = window._session.turns[-1]
    assert not reply.roll
    assert "не понимаю" not in reply.text
    assert window._session.world == before_world
    assert window._session.combat == before_combat
    assert window._session.dice.checkpoint() == checkpoint
    if question.startswith("что"):
        assert "Серый волк: враждебен" in window.journal.toPlainText()
        assert "10/10" not in window.journal.toPlainText()
    else:
        assert "Дорога у деревни" in reply.text


def test_export_contains_all_rolls_beyond_visible_history_without_modifying_session(
    window, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    for _ in range(102):
        window._run_command("бросить кубик")
    assert window.breakdown_selector.count() == 100
    before = window._session.to_dict()
    path = tmp_path / "расчёты.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_rolls_button.click()
    text = path.read_text(encoding="utf-8")
    assert "Действие №1: бросить кубик" in text
    assert "Бросок №1\nКубик с 20 гранями: 4" in text
    assert "Действие №102: бросить кубик" in text
    assert "Бросок №102" in text
    assert window._session.to_dict() == before
    assert window._dirty


def test_calculation_export_cannot_overwrite_slot(window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    window._run_command("проверить силу")
    window.save_slot(1)
    path = window._saves.directory / "slot-1.json"
    before = path.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window.export_rolls_button.click()
    assert warnings
    assert path.read_bytes() == before
