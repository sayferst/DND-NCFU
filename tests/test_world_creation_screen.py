"""The explicit hero -> loading -> story flow; all provider traffic is loopback."""

from copy import deepcopy

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from test_adventure import hero, world_value
from test_local_narrator import wait_for
from test_routerai import configure, router_server

from rpg_vkr.application import Session
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.creation_dialog import CreationDialog
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.ui.world_creation_screen import PHRASES, WorldCreationScreen


@pytest.fixture
def staging(qt_app, tmp_path, monkeypatch):
    window = MainWindow(session=hero(), saves=SaveSlots(tmp_path / "saves"))
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    window.resize(1280, 900)
    window.show()
    yield window
    window.ollama.cancel()
    window._dirty = False
    window.action_input.clear()
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def fill_hero(dialog):
    dialog.name_input.setText("Асуна")
    dialog.description_input.setPlainText("Путешественница с речных островов")
    dialog.world_brief_input.setPlainText("Свободное путешествие по магическим королевствам")
    return QDialog.DialogCode.Accepted


def test_form_waits_for_central_button_then_loading_opens_story(staging, qt_app, monkeypatch):
    monkeypatch.setattr(CreationDialog, "exec", fill_hero)
    with router_server(world_seed=world_value()) as (url, records):
        configure(staging, monkeypatch, url)
        staging.new_character()
        screen = staging.world_creation_screen
        assert staging.screen_stack.currentWidget() is screen and screen.isVisible()
        assert not staging.game_body.isVisible()
        assert screen.create_button.text() == "Создать новый мир"
        assert screen.create_button.isVisible() and screen.progress.isHidden()
        assert not records and not staging.ollama.busy
        before = deepcopy(staging._session.to_dict()), staging._session.dice.checkpoint()
        screen.create_button.click()
        assert screen.state == "busy"
        assert screen.progress.minimum() == screen.progress.maximum() == 0
        assert screen.flavor.text() in PHRASES
        assert screen.cancel_button.isVisible()
        assert not screen.create_button.isVisible()
        assert not staging.menuBar().isVisible()
        assert (staging._session.to_dict(), staging._session.dice.checkpoint()) == before
        wait_for(qt_app, lambda: not staging.ollama.busy)
        assert screen.state == "success" and screen.title.text() == "Мир создан"
        assert screen.progress.value() == screen.progress.maximum() == 100
        assert "Ветер шевелит ленты" in staging.journal.toPlainText()
        wait_for(qt_app, lambda: staging.screen_stack.currentWidget() is staging.game_body)
        assert staging.game_body.isVisible() and not screen.timer.isActive()
        assert "Ворота деревни" not in staging.journal.toPlainText()
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_animated_background_and_flavor_never_complete_the_world(qt_app):
    class Clock:
        def elapsed(self):
            return 11000

    session = hero()
    before = deepcopy(session.to_dict()), session.dice.checkpoint()
    screen = WorldCreationScreen()
    screen.resize(1000, 760)
    screen.show()
    try:
        screen.begin(session)
        qt_app.processEvents()
        initial = screen.grab().toImage()
        initial_phrase = screen.flavor.text()
        screen.elapsed = Clock()
        screen.animate()
        qt_app.processEvents()
        assert screen.flavor.text() != initial_phrase
        assert screen.grab().toImage() != initial
        assert screen.state == "busy" and screen.progress.maximum() == 0
        assert not session.generated_world
        assert (session.to_dict(), session.dice.checkpoint()) == before
        screen.hide()
        assert not screen.timer.isActive()
    finally:
        screen.close()


def test_cancel_returns_to_retry_screen_and_keeps_form(staging, qt_app, monkeypatch):
    monkeypatch.setattr(CreationDialog, "exec", fill_hero)
    with router_server(world_seed=world_value()) as (url, records):
        configure(staging, monkeypatch, url)
        staging.new_character()
        saved = deepcopy(staging._session.to_dict())
        screen = staging.world_creation_screen
        screen.create_button.click()
        screen.cancel_button.click()
        wait_for(qt_app, lambda: not staging.ollama.busy)
        assert screen.state == "error" and screen.create_button.isVisible()
        assert screen.progress.isHidden()
        assert "отменено" in screen.detail.text()
        assert staging._session.to_dict() == saved and not staging._session.generated_world
        assert not [r for r in records if r["method"] == "POST"]


def test_error_stays_on_loading_page_and_retry_uses_same_hero(staging, qt_app, monkeypatch):
    with router_server(world_seed="Неверный формат") as (url, records):
        configure(staging, monkeypatch, url)
        staging.resume_session()
        screen = staging.world_creation_screen
        session = staging._session
        screen.create_button.click()
        wait_for(qt_app, lambda: not staging.ollama.busy)
        assert staging.screen_stack.currentWidget() is screen
        assert screen.state == "error" and screen.title.text() == "Не удалось создать мир"
        assert "Мир не создан" in screen.detail.text()
        assert screen.progress.isHidden() and screen.menu_button.isVisible()
        assert len([r for r in records if r["method"] == "POST"]) == 2
    with router_server(world_seed=world_value()) as (url, records):
        configure(staging, monkeypatch, url)
        screen.create_button.click()
        wait_for(qt_app, lambda: not staging.ollama.busy)
        assert staging._session is session and session.generated_world
        assert screen.state == "success"
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_menu_and_continue_preserve_uncreated_hero_without_request(staging, monkeypatch):
    monkeypatch.setattr(CreationDialog, "exec", fill_hero)
    with router_server() as (url, records):
        configure(staging, monkeypatch, url)
        staging.new_character()
        saved = deepcopy(staging._session.to_dict())
        staging.world_creation_screen.menu_button.click()
        assert staging.screen_stack.currentWidget() is staging.game_body
        assert staging.tabs.tabText(staging.tabs.currentIndex()) == "Главное меню"
        assert "Мир ещё не создан" in staging.home_summary.text()
        assert "Ворота деревни" not in staging.home_summary.text()
        staging.resume_button.click()
        assert staging.screen_stack.currentWidget() is staging.world_creation_screen
        assert staging.world_creation_screen.state == "ready"
        assert staging._session.to_dict() == saved and not records


def test_old_success_transition_cannot_open_a_new_heros_uncreated_world(
    staging, qt_app, monkeypatch
):
    monkeypatch.setattr(CreationDialog, "exec", fill_hero)
    with router_server(world_seed=world_value()) as (url, records):
        configure(staging, monkeypatch, url)
        staging.resume_session()
        staging.world_creation_screen.create_button.click()
        wait_for(qt_app, lambda: not staging.ollama.busy)
        assert staging.world_creation_screen.state == "success"
        old = staging._session
        staging.new_character()
        assert staging._session is not old and not staging._session.generated_world
        QTest.qWait(800)
        assert staging.screen_stack.currentWidget() is staging.world_creation_screen
        assert staging.world_creation_screen.state == "ready"
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_historical_journal_stays_readable_without_starting_a_new_world(staging):
    staging._session = Session(seed=12)
    staging._session.submit("начать")
    staging._refresh_character()
    staging._render_journal()
    staging.resume_session()
    assert staging.screen_stack.currentWidget() is staging.game_body
    assert staging._session.turns and not staging.ollama.busy
