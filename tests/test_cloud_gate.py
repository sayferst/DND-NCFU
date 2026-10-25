"""Modern play never silently executes the old offline demonstration."""

from response_cases import new_session

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow


def test_offline_input_preserved_without_action_or_rng(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: calls.append(a))
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    try:
        before = window._session.to_dict(), window._session.dice.checkpoint()
        for text in ["осмотреться", "инвентарь", "атаковать", "бросить кубик"]:
            window.action_input.setText(text)
            window.submit_action()
            assert window.action_input.text() == text
            assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert len(calls) == 4
        assert "Стражник" not in window.journal.toPlainText()
        assert not window.chronicles_panel.entries
    finally:
        window.action_input.clear()
        window.close()


def test_generated_campaign_has_no_legacy_people(qt_app, tmp_path):
    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    try:
        assert all(
            e.key not in {"guard", "villager", "merchant"} for e in window.chronicles_panel.entries
        )
    finally:
        window.close()


def test_cloud_world_failure_never_starts_an_offline_world(qt_app, tmp_path):
    from test_adventure import hero

    from rpg_vkr.ui.adventure_panel import generation_failed

    session = hero()
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    try:
        before = session.to_dict(), session.dice.checkpoint()
        window._generating_session = session
        generation_failed(window, "Сеть недоступна")
        assert not session.generated_world
        assert (session.to_dict(), session.dice.checkpoint()) == before
        assert "Стражник" not in window.journal.toPlainText()
        assert window._generating_session is None and window.action_input.isEnabled()
    finally:
        window.close()
