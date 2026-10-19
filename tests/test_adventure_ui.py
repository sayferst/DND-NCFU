"""Real Qt plus local HTTP for the generated-world, notebook and contextual UI package."""

import json
from copy import deepcopy

from PySide6.QtWidgets import QMessageBox
from test_adventure import hero, started, world_value
from test_catalog_ui import enable, send
from test_local_narrator import wait_for
from test_routerai import router_server

from rpg_vkr.application import Session
from rpg_vkr.ui.adventure_panel import begin_world
from rpg_vkr.ui.context_actions import show_trade
from rpg_vkr.ui.main_window import MainWindow


def test_default_navigation_has_diary_and_no_permanent_shop_people_or_battle(qt_app, tmp_path):
    from rpg_vkr.storage.slots import SaveSlots

    window = MainWindow(session=Session(seed=1), saves=SaveSlots(tmp_path / "saves"))
    names = [window.navigation.itemText(i) for i in range(window.navigation.count())]
    assert "Дневник" in names
    assert not {"Жители", "Лавка", "Схватка", "Команды", "Кубики"}.intersection(names)
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def test_generated_world_request_uses_hero_and_world_inputs_and_persists(
    window, qt_app, monkeypatch
):
    window._session = hero()
    with router_server(world_seed=world_value()) as (url, records):
        enable(window, monkeypatch, url)
        begin_world(window)
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert window._session.generated_world
        assert window._session.current_place_name == "Пристань туманов"
        assert "янтарная птица" not in window.journal.toPlainText()
        posts = [r for r in records if r["method"] == "POST"]
        assert len(posts) == 1
        value = json.loads(posts[0]["body"]["messages"][1]["content"])
        assert "учителя" in value["hero_description"] and "Речное" in value["world_brief"]
        assert (
            window._campaign_repository.load(
                window._campaign_repository.identity(window._session)
            ).to_dict()
            == window._session.to_dict()
        )
        assert window.action_input.isEnabled()


def test_invalid_generation_retries_once_then_offline_fallback_preserves_description(
    window, qt_app, monkeypatch
):
    window._session = hero()
    bad = world_value()
    bad["start"] = "missing"
    with router_server(world_seed=bad) as (url, records):
        enable(window, monkeypatch, url)
        begin_world(window)
        wait_for(qt_app, lambda: not window.ollama.busy and window._generating_session is None)
        assert window._session.generated_world
        assert window._session.chronicle.seed.source == "offline-authored-1"
        assert "учителя" in window._session.campaign.raw_player_description
        assert len([r for r in records if r["method"] == "POST"]) == 2


def test_diary_all_controls_edit_pin_search_delete_save_and_load(window, monkeypatch):
    window._session = started()
    window._refresh_character()
    window.open_section("Дневник")
    window.diary_new.click()
    window.diary_title.setText("Травы у переправы")
    window.diary_text.setPlainText("Мята у старого моста. Со слов Рена.")
    window.diary_pin.setChecked(True)
    window.diary_save.click()
    entry = window._session.chronicle.entries[0]
    assert entry.pinned and entry.place == "Пристань туманов"
    window.diary_text.setPlainText("Мята у моста, проверено лично.")
    window.diary_save.click()
    assert len(window._session.chronicle.entries) == 1
    window.diary_search.setText("мята")
    assert window.diary_list.count() == 1
    window.save_slot(1)
    expected = deepcopy(window._session.to_dict())
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.diary_delete.click()
    assert not window._session.chronicle.entries
    window.load_slot(1)
    assert window._session.to_dict() == expected
    window.memory_query.setText("мята")
    window.memory_find.click()
    assert "мост" in window.memory_results.toPlainText()


def test_trade_window_buys_and_sells_actual_items_and_keeps_wallet_private(window):
    window._session = started()
    window._refresh_character()
    show_trade(window, "seller")
    dialog = window._trade_dialog
    assert "1000" not in dialog.status.text()
    dialog.quantity.setValue(1)
    dialog.execute.click()
    assert window._session.world.gold == 7
    assert window._session.turns[-1].trade.operation == "buy"
    current = window._trade_dialog
    current.mode.setCurrentIndex(1)
    row = next(i for i, r in enumerate(current.rows) if r[0] == "rope")
    current.table.selectRow(row)
    current.execute.click()
    assert window._session.world.gold == 9
    assert window._session.turns[-1].trade.operation == "sell"
    assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()


def test_chat_trade_previews_price_and_executes_before_writer(window, qt_app, monkeypatch):
    window._session = started()
    text = "куплю у Рена один бинт"
    plan = {
        "steps": [],
        "places": [],
        "check": "none",
        "trade": {"merchant_id": "seller", "item_id": "stock", "operation": "buy", "quantity": 1},
    }
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    with router_server(
        world_plans={text: plan}, writer_text="Рен передаёт вам свёрток перевязочной ткани."
    ) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert window._session.world.gold == 7
        assert window._session.turns[-1].trade
        assert len([r for r in records if r["method"] == "POST"]) == 2


def test_proposed_memory_is_used_by_writer_then_persisted_only_after_valid_story(
    window, qt_app, monkeypatch
):
    window._session = started()
    text = "спрошу Рена, где найти мяту"
    plan = {
        "steps": [],
        "places": [],
        "check": "none",
        "memories": [
            {
                "subject": "seller",
                "kind": "knowledge",
                "text": "Рен рассказал: мята растёт у старого моста",
                "importance": 4,
                "private": False,
            }
        ],
    }
    with router_server(
        world_plans={text: plan},
        writer_text=(
            "Рен указывает на тропу. «Мяту ищите у старого моста, где вода подходит к камням»."
        ),
    ) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert any("мята" in n.text for n in window._session.chronicle.memories)
        posts = [r for r in records if r["method"] == "POST"]
        payload = posts[1]["body"]["messages"][1]["content"]
        assert '"subject": "seller"' in payload and "мята растёт у старого моста" in payload


def test_new_world_attack_opens_context_panel_and_uses_real_counter_roll(
    window, qt_app, monkeypatch
):
    window._session = started()
    text = "атакую Рена"
    plan = {
        "steps": [],
        "places": [],
        "check": "none",
        "attempt": {
            "operation": "attack",
            "target_id": "seller",
            "lethal": False,
            "reason": "Попытка удара",
        },
    }
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    with router_server(
        world_plans={text: plan}, writer_text="Рен отшатывается и поднимает руку, защищая лицо."
    ) as (url, _):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        record = window._session.turns[-1].catalog
        assert record.counter and window._session.dice.checkpoint()[1] == 2
        assert window._encounter_dialog.isVisible()
        assert "seller" in window.journal.highlighter.hostile_ids
        assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()


def test_loaded_generated_campaign_opens_with_its_own_map(qt_app, tmp_path):
    from rpg_vkr.storage.slots import SaveSlots

    window = MainWindow(session=started(), saves=SaveSlots(tmp_path / "saves"))
    assert window.home_title.text() == "Карта переправы"
    assert window.known_places.rowCount() == 1
    assert window.known_places.item(0, 0).text() == "Пристань туманов"
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def test_trade_from_old_campaign_cannot_modify_new_hero_with_same_npc_id(window):
    window._session = started()
    window._refresh_character()
    show_trade(window, "seller")
    old_dialog = window._trade_dialog
    window._session = started()
    before = window._session.to_dict()
    old_dialog.submit()
    assert window._session.to_dict() == before
    assert not old_dialog.isVisible()


def test_diary_draft_requires_confirmation_to_discard(window, monkeypatch):
    from rpg_vkr.ui.adventure_panel import new_note

    window.diary_title.setText("Незавершённая запись")
    assert window._diary_draft
    monkeypatch.setattr(window, "_confirm", lambda _: False)
    new_note(window)
    assert window.diary_title.text() == "Незавершённая запись"
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    new_note(window)
    assert not window.diary_title.text() and not window._diary_draft


def test_restart_can_recover_working_database_without_a_json_slot(qt_app, tmp_path):
    from rpg_vkr.storage.campaigns import CampaignRepository
    from rpg_vkr.storage.slots import SaveSlots

    session = started()
    session.write_diary("Мост", "Встретить Рена у переправы", pinned=True)
    CampaignRepository(tmp_path / "campaigns.sqlite3").sync(session)
    window = MainWindow(session=Session(seed=1), saves=SaveSlots(tmp_path / "saves"))
    assert not list((tmp_path / "saves").glob("slot-*.json"))
    assert window.campaign_choice.count() == 1
    window.recover_campaign.click()
    assert window._session.to_dict() == session.to_dict()
    assert window.diary_list.count() == 1
    window._dirty = False
    window.close()
    window.deleteLater()
    qt_app.processEvents()
