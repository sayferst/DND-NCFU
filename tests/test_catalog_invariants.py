"""Resource conservation and adversarial state transitions, independent of data counts."""

from copy import deepcopy

import pytest
from test_catalog_campaign import act, started
from test_full_game_catalog import fixture_state, run

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as catalog
from rpg_vkr.domain.catalog_actions_v2 import trade
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.narrative.master import campaign_context


def coins(s):
    state = s.gameplay
    return (
        state["copper"]
        + s.world.gold * 100
        + state["living_world"]["treasury_cp"]
        + sum((e.state or {}).get("gold_cp", 0) for e in s.catalog.entities)
        + sum(f["treasury_cp"] for f in state["factions_v3"].values())
    )


def test_twenty_days_conserve_money_and_factions_spend_real_supplies():
    s = started("mage")
    before = coins(s)
    for _ in range(20):
        act(s, "wait", minutes=1440)
    assert coins(s) == before
    assert s.gameplay["living_world"]["day"] == 20
    faction = s.gameplay["factions_v3"]["workshop_guild"]
    assert faction["spent_cp"] > 0 and faction["treasury_cp"] < 1000
    assert s.gameplay["world_log"] and s.gameplay["known_factions"]
    public = campaign_context(s)
    assert "treasury_cp" not in str(public)
    assert "closed_until" not in str(public)
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_repeated_buy_sell_has_no_coin_or_item_creation():
    s = started("mage")
    initial = coins(s)
    stock = next(
        i for i in s.gameplay["items"] if i["owner"] == "seller" and i.get("template") == "mat_2_0"
    )
    player_money = s.gameplay["copper"]
    for _ in range(stock["quantity"]):
        act(s, "buy", merchant="seller", item=stock["id"])
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        act(s, "buy", merchant="seller", item=stock["id"])
    assert (s.to_dict(), s.dice.checkpoint()) == before
    bought = [
        i for i in s.gameplay["items"] if i.get("template") == "mat_2_0" and i["owner"] == "hero"
    ]
    for item in bought:
        act(s, "sell", merchant="seller", item=item["id"])
    assert coins(s) == initial and s.gameplay["copper"] < player_money
    assert s.gameplay["xp"] == 0


def test_magic_refund_never_produces_mp_and_source_materials_are_finite():
    state, ctx = fixture_state("mage")
    spell = next(
        r
        for r in catalog.available("spell")
        if r["effects"][0]["op"] == "restore_mp" and r["mode"] == "direct"
    )
    before = state["mp"]
    result = run(state, ctx, "cast", {"spell": spell["id"], "target": "hero"})
    assert result["state"]["mp"] < before
    state, ctx = fixture_state("artisan")
    state["living_world"]["nodes"][ctx["scene"]["current"]]["mat_0_0"] = 0
    with pytest.raises(ValueError, match="исчерпан"):
        run(state, ctx, "gather", {"material": "mat_0_0", "quantity": 1})


def test_tampered_cached_receipt_is_rejected_by_full_replay():
    s = started("mage")
    act(s, "cast", spell="light", target="hero")
    damaged = deepcopy(s.to_dict())
    damaged["snapshot"]["turns"][-1]["gameplay"]["receipt"]["summary"] = "Free fabricated reward"
    with pytest.raises(ValueError):
        Session.from_dict(damaged, version=31)


def test_unit_order_award_cannot_be_repeated_for_same_product():
    state, ctx = fixture_state("artisan")
    e = Engine(state, ctx, DiceRoller(seed=0), {})
    e.add_item("gear_sword_0_0", made_by="hero")
    goods = [i for i in e.state["items"] if i.get("made_by") == "hero"]
    for item in goods:
        trade(e, "sell", {"merchant": "seller", "item": item["id"]})
    xp = e.state["xp"]
    new = e.add_item("gear_sword_0_0", made_by="hero")
    trade(e, "sell", {"merchant": "seller", "item": new["id"]})
    assert e.state["xp"] == xp
