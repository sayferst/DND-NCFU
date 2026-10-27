from test_unified_rules import hero

from rpg_vkr.learning.embedded import load, retrieve
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.story import story_context


def test_embedded_knowledge_is_automatic_small_and_never_a_game_fact(tmp_path):
    assert len(load()) == 24
    s = hero()
    before = s.to_dict(), s.dice.checkpoint()
    context = story_context(build_frame(s), "deepseek/deepseek-v4.1-flash", "осматриваю чужой меч")
    hints = context["narrative_techniques"]
    assert 0 < len(hints) <= 3 and all(h["kind"] == "example_not_fact" for h in hints)
    assert (s.to_dict(), s.dice.checkpoint()) == before
    missing = tmp_path / "missing.json"
    assert not retrieve("меч", path=missing)
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema":"wrong"}', encoding="utf-8")
    assert not retrieve("меч", path=bad)


def test_library_is_absent_from_real_developer_navigation(qt_app, tmp_path):
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.main_window import MainWindow

    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    console = window.developer_console
    assert not hasattr(console, "learning")
    assert all(
        console.pages.tabText(i) != "Библиотека мастерства" for i in range(console.pages.count())
    )

    window.close()
