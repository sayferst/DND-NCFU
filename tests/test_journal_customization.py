"""Persisted accessible palettes, without changing text or game state."""

import json

import pytest
from PySide6.QtGui import QColor
from test_theme_notices import contrast

from rpg_vkr.ui.journal_colors import PRESETS, journal_palette
from rpg_vkr.ui.workspace_tools import ReadingPreferences, load_preferences, save_preferences


@pytest.mark.parametrize("name", PRESETS)
def test_presets_have_readable_roles(name):
    colors = journal_palette(name)
    for role, color in colors.items():
        if role != "background":
            assert contrast(QColor(color), QColor(colors["background"])) >= 4.5


def test_old_preferences_load_without_resetting_font(tmp_path):
    path = tmp_path / "reading.json"
    path.write_text(json.dumps({"font_size": 17, "theme": "Тёмная", "bold_text": False}))
    prefs, warning = load_preferences(path)
    assert not warning and prefs.font_size == 17 and not prefs.bold_text
    assert prefs.journal_theme == "Тёмное фэнтези"
    chosen = ReadingPreferences(
        journal_theme="Магический обсидиан", journal_colors={"npc": "#CCBBFF"}
    )
    save_preferences(path, chosen)
    assert load_preferences(path) == (chosen, "")


@pytest.mark.parametrize("colors", [{"npc": "red; color:red"}, {"secret": "#FFFFFF"}, []])
def test_invalid_css_and_unknown_roles_rejected(colors):
    with pytest.raises(ValueError):
        ReadingPreferences(journal_colors=colors)


def test_theme_switch_and_custom_color_do_not_change_journal_or_session(window):
    text, state = window.journal.toPlainText(), window._session.to_dict()
    window.journal_theme_choice.setCurrentText("Древний пергамент")
    window._journal_color_overrides["narrator"] = "#302020"
    window._change_reading()
    assert window.journal.highlighter.colour("narrator").name() == "#302020"
    assert window.journal.toPlainText() == text
    assert window._session.to_dict() == state
    assert load_preferences(window._preferences_path)[0].journal_colors == {"narrator": "#302020"}
    window._reset_reading()
    assert window.journal.highlighter.colour("narrator").name() == "#e8dfc9"
