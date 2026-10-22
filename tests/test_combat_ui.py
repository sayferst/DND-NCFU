"""Hostility is keyed by actor identity, with accessible labels and persistent style."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMessageBox

from rpg_vkr.ui.workspace_tools import ReadingPreferences, load_preferences


def tagged_blocks(window, actor_id):
    block = window.journal.document().firstBlock()
    result = []
    while block.isValid():
        metadata = block.userData()
        if metadata and metadata.actor_id == actor_id:
            result.append(block)
        block = block.next()
    return result


def test_only_present_targets_and_initial_hostile_mob_is_red(window):
    assert window.combat_targets.count() == 2
    assert window.combat_targets.currentData() == "guard"
    window._run_command("идти на дорогу")
    assert [window.combat_targets.itemData(i) for i in range(window.combat_targets.count())] == [
        "wolf",
        "boar",
    ]
    assert "Враждебен" in window.combat_targets.itemText(0)
    assert window.journal.actor_colour("wolf") != window.journal.actor_colour("boar")
    assert "10/10" not in window.target_description.text()


def test_neutral_attack_confirmation_can_be_cancelled(window, monkeypatch):
    before = window._session.to_dict()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.combat_attack.click()
    assert window._session.to_dict() == before
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.combat_attack.click()
    assert window._session.combat.actor("guard").disposition == "hostile"


def test_merchant_turns_red_and_trade_closes_and_colour_survives_load(window, monkeypatch, qt_app):
    for command in ("узнать дорогу на рынок", "идти на рынок", "подойти к торговцу"):
        window._run_command(command)
    neutral_colour = window.journal.actor_colour("merchant").name()
    window._run_command("поссориться с торговцем")
    qt_app.processEvents()
    hostile_colour = window.journal.actor_colour("merchant").name()
    assert neutral_colour != hostile_colour
    assert "Враждебен" in window.resident_list.item(2).text()
    assert not window.approach_merchant.isEnabled()
    assert "враждебен" in window.shop_reason.text()
    for block in tagged_blocks(window, "merchant"):
        formats = block.layout().formats()
        fmt = formats[0].format
        assert fmt.foreground().color().name() == hostile_colour
        assert fmt.fontWeight() == QFont.Weight.Bold
    window.save_slot(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.load_slot(1)
    qt_app.processEvents()
    assert window.journal.actor_colour("merchant").name() == hostile_colour
    window.theme_choice.setCurrentText("Тёмная")
    assert window.journal.actor_colour("merchant").name() == "#ff737d"
    assert window.journal.actor_colour("villager").name() != "#ff737d"


def test_default_text_is_larger_bold_and_user_can_change_it_without_game_mutation(window):
    assert window.journal.font().pointSize() == 13
    assert window.journal.font().bold()
    before = window._session.to_dict()
    window.bold_text.setChecked(False)
    assert not window.journal.font().bold()
    assert window._session.to_dict() == before
    assert load_preferences(window._preferences_path) == (
        ReadingPreferences(13, "Системная", False),
        "",
    )


def test_old_reading_preferences_increase_size_without_rewriting_file(tmp_path):
    path = tmp_path / "reading.json"
    content = '{"font_size": 11, "theme": "Тёмная"}'
    path.write_text(content, encoding="utf-8")
    assert load_preferences(path) == (ReadingPreferences(13, "Тёмная", True), "")
    assert path.read_text(encoding="utf-8") == content


def test_observation_shows_local_actors_with_colour_and_qualitative_health(window, qt_app):
    window._run_command("идти на дорогу")
    window._run_command("осмотреться")
    qt_app.processEvents()
    text = window.journal.toPlainText()
    assert "Серый волк враждебен, без видимых ран" in text
    assert "Кабан рядом" in text
    assert "10/10" not in text
    blocks = tagged_blocks(window, "wolf")
    assert blocks
    for block in blocks:
        formats = block.layout().formats()
        assert formats[0].format.foreground().color().name() == "#b00020"
