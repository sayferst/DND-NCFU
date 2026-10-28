"""Actual revision-three Session transactions, conservation and admission boundaries."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_adventure import world_value
from test_catalog_campaign import act
from test_catalog_invariants import coins

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as c
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.catalog_revision3 import build
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.domain.society import day, hourly, shipments
from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.unified_session import UnifiedSession, context


def started(class_id="warrior", seed=17, *, unconscious=False):
    s = UnifiedSession.create(
        Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True))),
        class_id,
        CLASSES[class_id][4],
        seed=seed,
        catalog_revision=3,
    )
    w = world_value()
    for a in w["entities"]:
        if a["id"] == "watcher":
            a["parent_id"] = "pier"
            if unconscious:
                a["state"].update(hp=0, life="unconscious")
    s.start_world(build_world(w, s, "revision-three-public-test"))
    return s


def test_data_three_rebuilds_without_rewriting_published_data():
    import hashlib

    expected = {
        "1": "ec77df664a3a4895e298272647054e2afad9acd880a26adda961c02ab6bed888",
        "2": "36bdcdc89d06f7d63f4991960ec02867f0b88f20202d125e1635eec4e6d93935",
    }
    for revision, sha in expected.items():
        assert (
            hashlib.sha256(Path(f"data/gameplay/catalog-v{revision}.json").read_bytes()).hexdigest()
            == sha
        )
    source = json.loads(Path("data/gameplay/catalog-v2.json").read_text(encoding="utf-8"))
    assert json.loads(Path("data/gameplay/catalog-v3.json").read_text(encoding="utf-8")) == build(
        source
    )
    with c.using(3):
        assert len(c.load()) == 3360


def test_registration_after_physical_action_and_alias_rejection():
    s = started()
    act(s, "check", task="perception", dc=10)
    d = Definition("new_guide_type", "Следопыт", "actor", ("npcs",), {"hp_max": 12})
    s.register_catalog(
        "Встречаю следопыта",
        [d],
        [Entity("new_guide", d.id, "pier", state={"hp": 12})],
        "Публичная сцена",
        "authored-integration",
    )
    assert s.actor_is_here("new_guide")
    before = s.to_dict(), s.dice.checkpoint()
    wrong = Definition(s.gameplay["items"][0]["id"], "Подмена", "actor", ("npcs",), {"hp_max": 12})
    with pytest.raises(ValueError):
        s.register_catalog(
            "Подмена предмета",
            [wrong],
            [Entity("other_guide", wrong.id, "pier")],
            "Недопустимая коллизия",
            "authored-integration",
        )
    assert (s.to_dict(), s.dice.checkpoint()) == before
    r = Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31)
    assert r.to_dict() == s.to_dict()


def test_bought_arrows_remain_ammunition_and_are_consumed_once():
    s = started("archer")
    arrow = next(i for i in s.gameplay["items"] if i["owner"] == "seller" and i.get("ammunition"))
    old_qty = sum(
        i["quantity"] for i in s.gameplay["items"] if i["owner"] == "hero" and i.get("ammunition")
    )
    act(s, "buy", merchant="seller", item=arrow["id"])
    assert (
        sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i["owner"] == "hero" and i.get("ammunition")
        )
        == old_qty + 1
    )
    act(s, "encounter", enemies=["watcher"])
    act(s, "attack", target="watcher")
    assert (
        sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i["owner"] == "hero" and i.get("ammunition")
        )
        == old_qty
    )
    r = Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31)
    assert r.to_dict() == s.to_dict() and r.dice.checkpoint() == s.dice.checkpoint()


def test_shop_roundtrip_cannot_create_money():
    s = started()
    item = s.gameplay["weapon"]
    act(s, "equip", item=item)
    before = coins(s)
    cp = s.gameplay["copper"]
    act(s, "sell", merchant="seller", item=item)
    act(s, "buy", merchant="seller", item=item)
    assert coins(s) == before and s.gameplay["copper"] < cp


def test_first_aid_uses_real_material_and_cannot_undo_death():
    s = started(seed=0, unconscious=True)
    bandage = next(i for i in s.gameplay["items"] if i.get("template") == "use_dressings_0_0")
    qty = bandage["quantity"]
    act(s, "first_aid", target="watcher", item=bandage["id"])
    assert sum(i["quantity"] for i in s.gameplay["items"] if i["id"] == bandage["id"]) == qty - 1
    # Controlled negative fixture: the same physical actor is now explicitly dead.
    e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {})
    from dataclasses import replace

    actor = e.actors["watcher"]
    e.actors["watcher"] = replace(actor, state={"hp": 0, "life": "dead"})
    from rpg_vkr.domain.field_actions import perform

    with pytest.raises(ValueError):
        perform(e, "first_aid", {"target": "watcher", "item": "start_3"})


def test_flee_is_a_real_battle_action_with_st_cost():
    s = started()
    act(s, "encounter", enemies=["watcher"])
    before_st = s.gameplay["st"]
    before_turns = len(s.turns)
    act(s, "flee", destination="path")
    assert len(s.turns) == before_turns + 1 and s.gameplay["st"] <= before_st - 3
    if s.gameplay["battle"] is None:
        assert s.interaction_state().current == "path"
    else:
        assert s.interaction_state().current == "pier"
    assert any(a.id == "watcher" for a in s.catalog.entities)


@pytest.mark.parametrize("days", [20, 90, 365])
def test_annual_simulation_conserves_coins_and_replays(days):
    s = started("mage")
    before = coins(s)
    for _ in range(days):
        act(s, "wait", minutes=1440)
    assert coins(s) == before
    w = s.gameplay["living_world"]
    state = w["society"]
    assert all(n >= 0 for stock in w["stocks"].values() for n in stock.values())
    assert all(
        0 <= p["water"] <= 20 and p["soil"] >= 0 and p["herbivores"] >= 0 and p["predators"] >= 0
        for p in state["places"].values()
    )
    restored = Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == s.dice.checkpoint()


def test_real_dispatch_is_debited_then_delayed_then_arrives():
    s = started()
    with c.using(3):
        e = Engine(s.gameplay, context(s), s.dice, {})
        w = e.state["living_world"]
        w["stocks"]["pier"]["food"] = 0
        w["stocks"]["path"]["food"] = 30
        shipments(e, 1)
        cargo = next(c for c in w["society"]["cargo"] if c["resource"] == "food")
        assert w["stocks"]["path"]["food"] == 26
        w.setdefault("blocked_until", {})["pier"] = 10 * 1440
        e.state["minute"] = 4 * 1440
        shipments(e, 4)
        assert cargo in w["society"]["cargo"] and cargo["delayed"]
        w["blocked_until"]["pier"] = 0
        shipments(e, 5)
        assert cargo not in w["society"]["cargo"]
        event = next(
            r
            for r in w["society"]["ledger"]
            if r["kind"] == "shipment_arrived" and r["shipment"] == cargo["id"]
        )
        assert event["after"] - event["before"] == 4 and event["cause"] == cargo["delayed"]


def test_hidden_remote_stock_does_not_guide_npc_route():
    s = started()
    with c.using(3):
        engines = [
            Engine(deepcopy(s.gameplay), context(s), DiceRoller(seed=7), {}) for _ in range(2)
        ]
        for e in engines:
            e.state["living_world"]["residents"]["seller"]["hunger"] = 4
            e.state["minute"] = 9 * 60
        engines[0].state["living_world"]["stocks"]["path"]["food"] = 0
        engines[1].state["living_world"]["stocks"]["path"]["food"] = 999
        for e in engines:
            hourly(e)
        assert engines[0].refs["seller"].place == engines[1].refs["seller"].place


def test_birth_creates_actual_dependent_actor_without_parent_secrets():
    s = started()
    with c.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=3), {})
        # Controlled household fixture with a real second adult and actual food.
        a = e.actors["watcher"]
        d = e.definitions[a.definition_id]
        e.definitions[d.id] = __import__("dataclasses").replace(
            d, categories=("npcs",), properties=d.properties | {"class": "resident"}
        )
        person = e.state["living_world"]["society"]["people"]["watcher"]
        person.update(civilian=True, mature=True)
        e.state["living_world"]["stocks"]["pier"]["food"] = 40
        old = set(e.actors)
        day(e, 90)
        children = set(e.actors) - old
        assert children
        for id in children:
            assert e.state["living_world"]["society"]["people"][id]["age_days"] == 0
            assert e.state["living_world"]["residents"][id]["job"] == "dependent"
            assert not any(
                "secret" in k for k in e.state["living_world"]["residents"][id]["knowledge"]
            )
