"""Player knowledge and physical presence limit both buttons and text commands."""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QPushButton

from rpg_vkr.application import Session
from rpg_vkr.domain.world import WorldState


def test_market_requires_directions_and_quest_can_supply_them():
    session = Session(seed=42)
    before = session.world
    assert "не знаете" in session.submit("идти на рынок").text
    assert session.world == before
    session.submit("узнать дорогу на рынок")
    assert session.world.market_known
    session.submit("идти на рынок")
    assert session.world.location == "market"
    assert not session.world.trading
    quest_session = Session()
    quest_session.submit("взять поручение")
    assert quest_session.world.market_known


def test_trade_cannot_be_bypassed_with_text_commands_and_closes_when_leaving():
    session = Session(seed=42)
    before = session.world
    session.submit("подойти к торговцу")
    assert session.world == before
    session.submit("узнать дорогу на рынок")
    session.submit("идти на рынок")
    before = session.world
    for command in ("купить бинт", "продать бинт"):
        assert "подойдите" in session.submit(command).text
        assert session.world == before
    offered = session.submit("подойти к торговцу")
    assert "В наличии: 3" in offered.text
    assert session.world.trading
    session.submit("купить бинт")
    assert session.world.gold == 7
    session.submit("идти к воротам")
    assert not session.world.trading
    session.submit("идти на рынок")
    assert not session.world.trading
    assert "подойдите" in session.submit("купить бинт").text
    assert session.submit("бросить d20").roll.value == 4


def test_npc_wallet_is_private_and_rejection_reveals_no_balance():
    session = Session(world=WorldState(location="market", market_known=True, shop_gold=0))
    for command in ("осмотреться", "поговорить", "подойти к торговцу", "торговля"):
        text = session.submit(command).text
        assert "деньги торговца" not in text.casefold()
        assert "золотых: 0" not in text
    before = session.world
    response = session.submit("продать бинт")
    assert "не готов выкупить" in response.text
    assert session.world == before


@pytest.mark.parametrize(
    "changes",
    [
        {"market_known": 1},
        {"trading": 1},
        {"trading": True},
        {"location": "market", "trading": True, "market_known": False},
    ],
)
def test_invalid_discovery_or_remote_trade_state_rejected(changes):
    with pytest.raises(ValueError):
        replace(WorldState(), **changes)


def test_inventory_contains_no_purchase_or_sale_controls(window):
    page = window.inventory_label.parentWidget()
    texts = [button.text().casefold() for button in page.findChildren(QPushButton)]
    assert not any("купить" in text or "продать" in text for text in texts)
    assert "купить бинт" not in window.quick_buttons


def test_shop_hides_prices_stock_and_wallet_until_contact(window, qt_app):
    window.open_section("Лавка")
    qt_app.processEvents()
    assert not window.shop_buy.isVisible()
    assert not window.shop_sell.isVisible()
    assert "В наличии" not in window.shop_summary.text()
    assert not window.travel_buttons["market"].isEnabled()
    window.ask_market.click()
    window.travel_buttons["market"].click()
    qt_app.processEvents()
    assert not window.shop_buy.isVisible()
    window.approach_merchant.click()
    qt_app.processEvents()
    assert window.shop_buy.isVisible()
    assert "В наличии: 3" in window.shop_summary.text()
    assert "деньги торговца" not in window.shop_summary.text().casefold()
    window._session.world = replace(window._session.world, shop_gold=0)
    window._refresh_character()
    assert window.shop_sell.isEnabled()  # The player does not know the merchant's wallet.
    before = window._session.world
    window.shop_sell.click()
    assert window._session.world == before
    assert "не готов выкупить" in window.shop_reply.toPlainText()
    window.travel_buttons["gate"].click()
    qt_app.processEvents()
    assert not window.shop_buy.isVisible()
    assert "В наличии" not in window.shop_summary.text()
