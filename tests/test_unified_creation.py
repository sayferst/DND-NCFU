import pytest
from PySide6.QtWidgets import QCheckBox, QDialogButtonBox, QScrollArea

from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.ui.creation_dialog import CreationDialog


@pytest.mark.parametrize("key", CLASSES)
def test_four_pages_one_class_one_talent_and_real_session(qt_app, key):
    d = CreationDialog()
    d.class_choice.setCurrentIndex(d.class_choice.findData(key))
    assert d.creation_steps.count() == 4 and not d.findChildren(QCheckBox)
    assert d.initial_talent.count() == 6
    d.description_input.setPlainText("Эльф,32года; кузница семьи.")
    d.world_brief_input.setPlainText("Тихое фэнтези")
    assert not d.buttons.button(QDialogButtonBox.StandardButton.Ok).isVisible()
    for _ in range(3):
        d.step(1)
    s = d.create_session()
    frame = build_frame(s)
    ctx = campaign_context(s, query="Мастер, осматриваюсь")
    assert (
        s.gameplay["identity"]["class_id"] == key
        and s.campaign.raw_player_description == "Эльф,32года; кузница семьи."
    )
    assert CLASSES[key][0] in frame.hero
    assert ctx["d20_skills"] is None
    assert len(s.gameplay["talents"]) == 1
    d.scores["strength"].setValue(8)
    if key != "mage":
        assert not d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    d.resize(600, 620)
    d.show()
    qt_app.processEvents()
    assert all(a.horizontalScrollBar().maximum() == 0 for a in d.findChildren(QScrollArea))
    d.close()
