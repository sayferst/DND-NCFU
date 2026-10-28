"""Deterministic finite policies, actual engine changes and public provenance."""

import json

import pytest
from test_catalog_campaign import act
from test_catalog_invariants import coins
from test_completion_revision import new_session

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.catalog_world import apply_event
from rpg_vkr.domain.causal_world import day
from rpg_vkr.unified_session import context


@pytest.mark.parametrize("days", [20, 90, 100, 365])
def test_twenty_ninety_year_policies_replay(days):
    s = new_session()
    initial_coins = coins(s)
    for _ in range(days):
        act(s, "wait", minutes=1440)
    w = s.gameplay["living_world"]
    assert coins(s) == initial_coins
    assert w["day"] >= days
    assert all(n >= 0 for stock in w["stocks"].values() for n in stock.values())
    assert all(n >= 0 for n in w["reserve"].values())
    assert all(0 <= e["herbivores"] <= e["capacity"] for e in w["causal"]["ecology"].values())
    restored = Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == s.dice.checkpoint()


def test_closed_road_cargo_is_debited_then_delayed_then_delivered():
    s = new_session()
    with content.using(2):
        e = Engine(s.gameplay, context(s), s.dice, {})
        w = e.state["living_world"]
        place = e.scene.current
        w["stocks"][place]["food"] = 0
        flood = next(r for r in content.available("event") if r["op"] == "flood")
        assert apply_event(e, flood, place)
        w["blocked_until"][place] = 10 * 1440
        before = w["reserve"]["mat_2_0"]
        day(e, 1)
        shipment = next(s for s in w["causal"]["shipments"] if s["destination"] == place)
        assert w["reserve"]["mat_2_0"] < before
        e.state["minute"] = 3 * 1440
        day(e, 3)
        assert shipment in w["causal"]["shipments"] and shipment["blocked"]
        w["blocked_until"][place] = 0
        e.state["minute"] = 4 * 1440
        day(e, 4)
        assert shipment not in w["causal"]["shipments"]
        arrived = next(
            v
            for v in w["causal"]["chains"]
            if v["kind"] == "shipment_arrived" and v["shipment"] == shipment["id"]
        )
        assert arrived["after"] - arrived["before"] == shipment["quantity"]
        assert arrived["cause"] == shipment["blocked"]
