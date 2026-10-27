"""Modern Qt lifecycle against a loopback provider; never calls a live model."""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog
from test_adventure import hero, world_value
from test_local_narrator import wait_for
from test_routerai import configure, router_server

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.adventure_panel import begin_world
from rpg_vkr.ui.creation_dialog import CreationDialog
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.visuals.context import scene_target


@pytest.fixture
def modern(qt_app, tmp_path):
    window = MainWindow(session=hero(), saves=SaveSlots(tmp_path / "saves"))
    yield window
    window.ollama.cancel()
    window._dirty = False
    window.action_input.clear()
    window.close()
    window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("action", ["начать", "осмотреться", "инвентарь", "идти на дорогу"])
def test_configured_master_cannot_play_a_hero_without_a_world(modern, monkeypatch, action):
    with router_server() as (url, records):
        configure(modern, monkeypatch, url)
        before = deepcopy(modern._session.to_dict()), modern._session.dice.checkpoint()
        modern.action_input.setText(action)
        modern.submit_action()
        assert modern.action_input.text() == action
        assert (modern._session.to_dict(), modern._session.dice.checkpoint()) == before
        assert not modern.ollama.busy and not records
        assert "Ворота деревни" not in modern.journal.toPlainText()


def test_generation_cannot_be_cancelled_by_chat_or_repeated_start(modern, monkeypatch, qt_app):
    with router_server(world_seed=world_value()) as (url, records):
        configure(modern, monkeypatch, url)
        begin_world(modern)
        turn_id = modern.ollama.turn_id
        modern.action_input.setText("начать")
        assert not modern.send_button.isEnabled()
        modern.submit_action()
        assert modern._generating_session is modern._session
        assert modern.ollama.turn_id == turn_id
        begin_world(modern)
        assert modern.ollama.turn_id == turn_id
        wait_for(qt_app, lambda: not modern.ollama.busy)
        assert modern._session.generated_world and not modern._session.turns
        assert modern.action_input.text() == "начать"
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_invalid_world_has_visible_error_and_can_retry_same_hero(modern, monkeypatch, qt_app):
    with router_server(world_seed="Это рассказ вместо объекта мира") as (url, records):
        configure(modern, monkeypatch, url)
        before = deepcopy(modern._session.to_dict()), modern._session.dice.checkpoint()
        begin_world(modern)
        wait_for(qt_app, lambda: not modern.ollama.busy)
        assert modern._generating_session is None and not modern._session.generated_world
        assert (modern._session.to_dict(), modern._session.dice.checkpoint()) == before
        assert len([r for r in records if r["method"] == "POST"]) == 2
        assert "Мир не создан" in modern.journal.toPlainText()
        assert modern.world_retry_button.isEnabled()
        assert "Ворота деревни" not in modern.map_location.text()
    with router_server(world_seed=world_value()) as (url, records):
        configure(modern, monkeypatch, url)
        modern.world_retry_button.click()
        wait_for(qt_app, lambda: not modern.ollama.busy)
        assert modern._session.generated_world
        assert modern.scene_title.text() == "Пристань туманов"
        assert scene_target(modern._session)
        assert "Мир не создан" not in modern.journal.toPlainText()
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_new_legend_creates_and_persists_its_world_before_starting_chat(
    modern, monkeypatch, qt_app
):
    brief = (Path(__file__).parents[1] / "docs/research/USER_WORLD_BRIEF_2026-10-21.txt").read_text(
        encoding="utf-8"
    )

    def create(dialog):
        dialog.name_input.setText("Асуна")
        dialog.world_brief_input.setPlainText(brief)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CreationDialog, "exec", create)
    monkeypatch.setattr(modern, "_confirm", lambda _: True)
    reply = "Над причалом хлопает парус. Рен оборачивается к Асуне и ждёт вопроса."
    with router_server(
        world_seed=world_value(),
        world_plans={"начать": {"steps": [], "places": [], "check": "none", "reply": reply}},
    ) as (url, records):
        configure(modern, monkeypatch, url)
        modern.new_character()
        assert modern.ollama.busy
        assert modern.screen_stack.currentWidget() is modern.world_creation_screen
        wait_for(qt_app, lambda: not modern.ollama.busy)
        assert modern._session.generated_world
        assert modern._session.character.name == "Асуна"
        assert modern._session.campaign.world_brief == brief
        modern.action_input.setText("начать")
        modern.submit_action()
        wait_for(qt_app, lambda: not modern.ollama.busy)
        assert "Ворота деревни" not in modern.journal.toPlainText()
        assert "яблок" not in modern.journal.toPlainText()
        assert reply in modern.journal.toPlainText()
        assert scene_target(modern._session)
        targets = []
        monkeypatch.setattr(modern.visuals, "request", lambda target: targets.append(target))
        modern.scene_image_button.click()
        assert len(targets) == 1 and "Пристань туманов" in targets[0].brief
        saved = modern._session.to_dict()
        modern.save_slot(1)
        modern.load_slot(1)
        assert modern._session.to_dict() == saved
        repository = modern._campaign_repository
        assert repository.load(repository.identity(modern._session)).to_dict() == saved
        assert len([r for r in records if r["method"] == "POST"]) == 2
        posts = [r for r in records if r["method"] == "POST"]
        genesis = json.loads(posts[0]["body"]["messages"][1]["content"])
        assert genesis["world_brief"] == brief
        assert "Ворота деревни" not in str(genesis)
        planning = json.loads(posts[1]["body"]["messages"][1]["content"])
        assert planning["world_brief"] == brief


def test_draft_campaign_is_named_as_unfinished(modern):
    rows = modern._campaign_repository.list_campaigns()
    assert len(rows) == 1
    assert "Мир ещё не создан" in rows[0][2]


def test_reopened_draft_updates_old_label_without_rewriting_history(modern):
    from rpg_vkr.storage.campaigns import CampaignRepository

    repository = modern._campaign_repository
    campaign = repository.identity(modern._session)
    with closing(sqlite3.connect(repository.path)) as db, db:
        db.execute("UPDATE campaigns SET title='Учебная кампания' WHERE id=?", (campaign,))
        before = db.execute(
            "SELECT revision,digest,payload FROM campaigns WHERE id=?", (campaign,)
        ).fetchone()
    reopened = CampaignRepository(repository.path)
    restored = reopened.load(campaign)
    reopened.sync(restored)
    assert reopened.list_campaigns()[0][2] == "Мир ещё не создан"
    with closing(sqlite3.connect(repository.path)) as db:
        after = db.execute(
            "SELECT revision,digest,payload FROM campaigns WHERE id=?", (campaign,)
        ).fetchone()
    assert after == before


def test_old_turn_without_world_never_changes_draft_into_village(modern, monkeypatch):
    modern._session.submit("начать")  # Reproduce the previous release's contaminated draft.
    modern._refresh_character()
    modern._render_journal()
    with router_server() as (url, records):
        configure(modern, monkeypatch, url)
        before = deepcopy(modern._session.to_dict())
        modern.action_input.setText("начать")
        modern.submit_action()
        assert modern._session.to_dict() == before
        assert not modern.ollama.busy and not records
        assert modern.scene_title.text() == "Мир ещё не создан"


def test_recovery_keeps_old_history_slots_and_original_hero_brief(modern, monkeypatch, qt_app):
    modern._session.submit("начать")
    modern._session.submit("осмотреться")
    modern._refresh_character()
    modern.save_slot(1)
    old = modern._session
    saved = deepcopy(old.to_dict())
    original_slot = (modern._saves.directory / "slot-1.json").read_bytes()
    monkeypatch.setattr(modern, "_confirm", lambda _: False)
    with router_server(world_seed=world_value()) as (url, records):
        configure(modern, monkeypatch, url)
        modern.world_retry_button.click()
        assert modern._session is old and not records and not modern.ollama.busy
        monkeypatch.setattr(modern, "_confirm", lambda _: True)
        modern.world_retry_button.click()
        wait_for(qt_app, lambda: not modern.ollama.busy)
        current = modern._session
        assert current is not old and current.generated_world and not current.turns
        assert current.character == old.progress.initial
        assert current.campaign.raw_player_description == old.campaign.raw_player_description
        assert current.campaign.world_brief == old.campaign.world_brief
        assert modern._current_slot is None
        assert (modern._saves.directory / "slot-1.json").read_bytes() == original_slot
        repository = modern._campaign_repository
        assert repository.load(repository.identity(old)).to_dict() == saved
        assert repository.identity(current) != repository.identity(old)
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_local_prompt_error_is_visible_and_does_not_leave_generation_stuck(modern, monkeypatch):
    import rpg_vkr.narrative.instructions as instructions

    def unavailable():
        raise ValueError("Не удалось прочитать инструкцию мастера")

    with router_server() as (url, records):
        configure(modern, monkeypatch, url)
        monkeypatch.setattr(instructions, "load_instructions", unavailable)
        begin_world(modern)
        assert modern._generating_session is None and not modern.ollama.busy and not records
        assert "Не удалось прочитать" in modern.journal.toPlainText()
        assert modern.world_retry_button.isEnabled()


def test_access_failure_does_not_retry_or_replace_world_with_demo(modern, monkeypatch, qt_app):
    with router_server(chat_status=401) as (url, records):
        configure(modern, monkeypatch, url)
        begin_world(modern)
        wait_for(qt_app, lambda: not modern.ollama.busy)
        assert modern._generating_session is None and not modern._session.generated_world
        assert not modern._session.turns
        assert "401" in modern.world_start_status.text()
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_packaged_creation_probe_ignores_and_preserves_personal_prompt(
    qt_app, tmp_path, monkeypatch
):
    from test_adventure import started

    from rpg_vkr.narrative import instructions
    from rpg_vkr.packaged_probe import world_creation_probe

    personal = tmp_path / "personal-master.txt"
    personal.write_bytes(b"")
    monkeypatch.setattr(instructions, "LOCAL_PATH", personal)
    world_creation_probe(qt_app, tmp_path / "probe", started().chronicle.seed)
    assert personal.read_bytes() == b"" and instructions.LOCAL_PATH == personal
