"""Actual UI paths for the existing world, with temporary player data only."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from rpg_vkr.application import Session
from rpg_vkr.ui.main_window import MainWindow


def test_default_start_menu_and_resume_preserve_session(window, qt_app):
    other = MainWindow(saves=window._saves)
    try:
        assert other.tabs.tabText(other.tabs.currentIndex()) == "Главное меню"
        before = other._session.to_dict()
        other.resume_button.click()
        assert other.tabs.currentIndex() == 0
        assert other._session.to_dict() == before
    finally:
        other.close()
        other.deleteLater()
        qt_app.processEvents()


def test_navigation_selection_and_programmatic_changes_stay_in_sync(window):
    for name in ("Карта", "Лавка", "Жители", "Сохранения", "Как играть", "Главное меню"):
        index = window.navigation.findText(name)
        window.navigation.setCurrentIndex(index)
        assert window.tabs.tabText(window.tabs.currentIndex()) == name
    window.focus_journal_search()
    assert window.navigation.currentText() == "Приключение"
    window.open_section("Кубики")
    assert window.navigation.currentText() == "Кубики"


def test_menu_return_keeps_draft_unsaved_world_and_random_state(window, qt_app):
    window._run_command("взять поручение")
    window.action_input.setText("мой черновик")
    before = window._session.to_dict()
    window.activateWindow()
    qt_app.processEvents()
    QTest.keyClick(window, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier)
    assert window.navigation.currentText() == "Главное меню"
    window.resume_button.click()
    assert window._session.to_dict() == before
    assert window.action_input.text() == "мой черновик"
    assert window._dirty


def test_map_travel_and_one_time_exploration_update_all_views(window):
    assert not window.travel_buttons["gate"].isEnabled()
    assert not window.map_explore.isEnabled()
    window.travel_buttons["road"].click()
    assert "Дорога" in window.map_location.text()
    assert window.map_explore.isEnabled()
    window.map_explore.click()
    assert window._session.world.hp == 9
    assert not window.map_explore.isEnabled()
    assert "уже исследована" in window.exploration_status.text()
    assert "#1" in window.roll_history.toPlainText()
    before = window._session.to_dict()
    window.map_explore.click()
    assert window._session.to_dict() == before


def test_residents_have_location_guard_and_show_real_conversation(window):
    window.resident_list.setCurrentRow(2)
    assert not window.resident_talk.isEnabled()
    assert "Сначала" in window.resident_description.text()
    if not window._session.world.market_known:
        window.ask_market.click()
    window.travel_buttons["market"].click()
    assert window.resident_talk.isEnabled()
    window.resident_talk.click()
    assert "Подойдите" in window.resident_reply.toPlainText()
    assert window._session.turns[-1].action == "поговорить"
    window.travel_buttons["gate"].click()
    window.resident_list.setCurrentRow(1)
    assert window.resident_talk.isEnabled()
    window.resident_talk.click()
    assert "Заплачу 5" in window.resident_reply.toPlainText()
    assert window._session.world.quest == "available"
    window.resident_help.click()
    assert "Жительница благодарит" in window.resident_reply.toPlainText()
    window.resident_quest.click()
    assert window._session.world.quest == "active"
    assert not window.resident_quest.isEnabled()


def test_shop_buttons_balance_money_items_and_stock(window):
    assert not window.shop_buy.isEnabled()
    assert "подхода к торговцу" in window.shop_reason.text()
    if not window._session.world.market_known:
        window.ask_market.click()
    window.travel_buttons["market"].click()
    window.approach_merchant.click()
    initial = window._session.world
    window.shop_buy.click()
    state = window._session.world
    assert (state.gold, state.bandages, state.shop_stock, state.shop_gold) == (7, 2, 2, 23)
    assert "В наличии: 2" in window.shop_summary.text()
    assert state.gold + state.shop_gold == initial.gold + initial.shop_gold
    window.shop_sell.click()
    assert (window._session.world.gold, window._session.world.bandages) == (8, 1)
    assert window.inventory_table.item(0, 1).text() == "1"


def test_shop_unavailable_reasons_do_not_change_resources(window):
    window._session = Session(
        world=replace(
            window._session.world,
            location="market",
            market_known=True,
            trading=True,
            gold=0,
            bandages=0,
            shop_stock=0,
            shop_gold=0,
        )
    )
    window._refresh_character()
    assert not window.shop_buy.isEnabled()
    assert not window.shop_sell.isEnabled()
    reason = window.shop_reason.text()
    assert "не хватает золота" in reason
    assert "нет бинтов" in reason
    assert "деньги торговца" not in reason
    before = window._session.to_dict()
    window.shop_buy.click()
    window.shop_sell.click()
    assert window._session.to_dict() == before


def test_inventory_shows_only_owned_items_and_cannot_edit_counts(window):
    from PySide6.QtWidgets import QAbstractItemView

    assert window.inventory_table.rowCount() == 1
    assert window.inventory_table.item(0, 0).text() == "Бинт"
    assert window.inventory_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    window._run_command("взять поручение")
    assert window.inventory_table.rowCount() == 2
    assert window.inventory_table.item(1, 0).text() == "Корзина поручения"
    if not window._session.world.market_known:
        window.ask_market.click()
    window.travel_buttons["market"].click()
    window._run_command("доставить корзину")
    assert window.inventory_table.rowCount() == 1


def test_dice_panel_uses_shared_rng_and_keeps_typed_draft(window):
    window.action_input.setText("черновик")
    window.check_choice.setCurrentIndex(1)
    window._run_command(window.check_choice.currentData())
    assert window._session.turns[-1].roll.value == 4
    assert window._session.turns[-1].check.ability == "dexterity"
    window._run_command("бросить d20")
    assert window._session.turns[-1].roll.value == 1
    assert "#2" in window.roll_history.toPlainText()
    assert "Бросков в сессии: 2" in window.roll_summary.text()
    assert window.action_input.text() == "черновик"
    window.font_size.setValue(18)
    assert window.roll_history.font().pointSize() == 18


def test_roll_history_shows_recent_100_without_truncating_session(window):
    for _ in range(102):
        window._run_command("бросить d20")
    history = window.roll_history.toPlainText()
    assert history.startswith("#3 ·")
    assert "#102 ·" in history
    assert len(window._session.turns) == 102
    assert "Мастер: На кубике выпало" in window.journal.toPlainText()
    assert window.breakdown_selector.count() == 100
    assert window.breakdown_selector.itemData(0) == 2


def test_loading_restores_map_shop_inventory_quest_dice_and_returns_to_game(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._run_command("взять поручение")
    window.travel_buttons["road"].click()
    window.map_explore.click()
    window.save_slot(1)
    saved = window._session.to_dict()
    if not window._session.world.market_known:
        window.ask_market.click()
    window.travel_buttons["market"].click()
    window._run_command("доставить корзину")
    window.shop_buy.click()
    window.open_section("Главное меню")
    window.load_slot(1)
    assert window._session.to_dict() == saved
    assert window.navigation.currentText() == "Приключение"
    assert "Дорога" in window.map_location.text()
    assert not window.map_explore.isEnabled()
    assert not window.shop_buy.isEnabled()
    assert window.inventory_table.rowCount() == 2
    assert window.quest_progress.value() == 1
    assert "#1" in window.roll_history.toPlainText()


def test_bad_load_from_menu_does_not_reset_current_game_or_navigation(window, monkeypatch):
    window._run_command("помочь")
    window.save_slot(1)
    (window._saves.directory / "slot-1.json").write_text("{broken", encoding="utf-8")
    window.open_section("Главное меню")
    before = window._session.to_dict()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window.load_slot(1)
    assert window._session.to_dict() == before
    assert window.navigation.currentText() == "Главное меню"


def test_fullscreen_and_escape_preserve_current_game(window, qt_app):
    window._run_command("помочь")
    before = window._session.to_dict()
    window.fullscreen_action.trigger()
    qt_app.processEvents()
    assert window.isFullScreen()
    assert window.fullscreen_action.isChecked()
    window.activateWindow()
    qt_app.processEvents()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    qt_app.processEvents()
    assert not window.isFullScreen()
    assert not window.fullscreen_action.isChecked()
    assert window._session.to_dict() == before


def test_close_from_menu_can_be_cancelled_without_discarding_draft(window, monkeypatch):
    window.action_input.setText("черновик")
    window.open_section("Главное меню")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert not window.close()
    assert window.action_input.text() == "черновик"
    assert window.isVisible()
