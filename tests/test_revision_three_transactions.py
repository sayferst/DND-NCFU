"""Revision-three regressions at real transaction and historical save boundaries."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_catalog_campaign import act
from test_society_campaign import started

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.domain.society import apply_event, emit
from rpg_vkr.storage.update_probe import verify
from rpg_vkr.unified_session import context


def test_actual_published_writer_two_fixture_and_next_d100_are_unchanged():
    path = Path("docs/validation/final-campaign-2026-10-28/published-catalog2-save.json")
    raw = path.read_bytes()
    saved = json.loads(raw)
    assert saved["source_commit"] == "e6bb2373247873ae4074700259ea56e163faf2ec"
    session = Session.from_dict(saved["session"], version=saved["schema_version"])
    assert json.loads(json.dumps(session.to_dict())) == saved["session"]
    result = asdict(session.dice.roll("1d100", reason="compatibility continuation"))
    result["individual_rolls"] = list(result["individual_rolls"])
    assert result == saved["next_d100"]
    assert path.read_bytes() == raw and session.gameplay["catalog_revision"] == 2


def test_actual_previous_world_three_replays_with_identical_next_roll():
    path = Path("docs/validation/final-campaign-2026-10-28/published-world3-save.json")
    saved = json.loads(path.read_bytes())
    session = Session.from_dict(saved["session"], version=31)
    assert json.loads(json.dumps(session.to_dict())) == saved["session"]
    assert "world_policy" not in session.gameplay
    result = asdict(session.dice.roll("1d100", reason="compatibility continuation"))
    result["individual_rolls"] = list(result["individual_rolls"])
    assert result == saved["next_d100"]


def test_food_production_catalog_only_accepts_edible_input():
    s = started("artisan")
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {})
        row = next(r for r in content.load().values() if r.get("op") == "production")
        assert all(
            r["resource"] == "mat_2_0"
            for r in content.load().values()
            if r.get("op") == "production"
        )
        stock = e.state["living_world"]["stocks"][e.scene.current]
        stock["mat_0_0"] = 100
        stock["mat_2_0"] = 100
        food = stock["food"]
        assert apply_event(e, row)
        assert stock["food"] == food + row["amount"] * 2
        assert stock["mat_0_0"] == 100 and stock["mat_2_0"] == 100 - row["amount"]


def test_bulk_shop_preserves_quantity_and_coins_and_rejects_overdraft():
    s = started("archer")
    item = next(i for i in s.gameplay["items"] if i["owner"] == "seller" and i.get("ammunition"))
    before = item["quantity"]
    initial = sum(i["quantity"] for i in s.gameplay["items"] if i.get("ammunition"))
    act(s, "buy", merchant="seller", item=item["id"], quantity=3)
    assert next(i for i in s.gameplay["items"] if i["id"] == item["id"])["quantity"] == before - 3
    assert sum(i["quantity"] for i in s.gameplay["items"] if i.get("ammunition")) == initial
    previous = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        act(s, "buy", merchant="seller", item=item["id"], quantity=before)
    assert (s.to_dict(), s.dice.checkpoint()) == previous


def test_reported_damage_is_actual_hp_loss_including_overkill_and_absorption():
    s = started()
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {})
        hp = e.hp("watcher")
        assert e.damage("watcher", 999) == hp and e.hp("watcher") == 0
        assert e.damage("watcher", 999) == 0
        e.status("hero", "shield", 999, 10)
        hp = e.hp("hero")
        assert e.damage("hero", 1) == 0 and e.hp("hero") == hp


def test_gold_is_converted_once_preserving_total_value():
    s = started()
    ctx = context(s)
    ctx["world"]["gold"] = 7
    with content.using(3):
        e = Engine(s.gameplay, ctx, DiceRoller(seed=0), {})
        assert e.world.gold == 0 and e.state["copper"] == s.gameplay["copper"] + 700


def test_new_faction_treasury_is_funded_and_player_membership_transfers_coins():
    from rpg_vkr.domain.contracts import faction_action

    s = started()
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {})
        a = e.actors["seller"]
        d = e.definitions[a.definition_id]
        e.definitions[d.id] = replace(
            d,
            properties=dict(d.properties)
            | {"faction_id": "test_guild", "faction_name": "Гильдия дороги"},
        )
        from rpg_vkr.domain.society import initialize

        wallet = a.state["gold_cp"]
        initialize(e)
        f = e.state["factions_v3"]["test_guild"]
        assert f["treasury_cp"] == min(25, wallet)
        assert e.actors[a.id].state["gold_cp"] == wallet - f["treasury_cp"]
        cp = e.state["copper"]
        treasury = f["treasury_cp"]
        faction_action(e, {"faction": f["id"], "operation": "join"})
        faction_action(e, {"faction": f["id"], "operation": "donate", "amount": 17})
        assert e.state["copper"] == cp - 27 and f["treasury_cp"] == treasury + 27
        assert e.state["known_factions"][f["id"]]["reputation"] == f["reputation"]
        assert f["id"] in e.state["memberships"]
        with pytest.raises(ValueError):
            faction_action(e, {"faction": f["id"], "operation": "join"})
        faction_action(e, {"faction": f["id"], "operation": "leave"})
        assert not e.state["memberships"]


def test_rumor_is_not_confirmed_knowledge_or_hidden_source_fact():
    s = started()
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {})
        event = next(r for r in content.load().values() if r.get("op") == "exchange_news")
        for p in e.state["living_world"]["society"]["people"].values():
            p["civilian"] = True
        emit(e, "resource_observed", e.scene.current, resource=event["resource"])
        people = sorted(e.refs)
        recipient = people[(event["role"] + 1) % len(people)]
        resident = e.state["living_world"]["residents"][recipient]
        resident["knowledge"] = []
        assert apply_event(e, event)
        rumor = resident["rumors"][-1]
        assert not rumor["confirmed"] and rumor["event_id"] not in resident["knowledge"]
        assert not apply_event(e, event)


def test_installed_reader_verifies_old_writer_without_writing(tmp_path):
    from scripts.probe_saved_campaign import probe

    directory = tmp_path / "isolated"
    probe(directory, "create")
    path = directory / "saves/slot-1.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert verify(directory)["ok"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes"):
        verify(directory)


def test_raw_deposits_are_accessible_with_tools_and_are_finite():
    from rpg_vkr.domain.catalog_actions_v2 import perform

    s = started("artisan")
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {"material": "mat_0_0"})
        w = e.state["living_world"]
        node = w["nodes"][e.scene.current]
        deposit = w["society"]["places"][e.scene.current]["deposits"]
        node["mat_0_0"] = 0
        before = deposit["mat_0_0"]
        for _ in range(20):
            perform(e, "gather", {"material": "mat_0_0", "quantity": 2})
            if deposit["mat_0_0"] < before:
                break
        assert deposit["mat_0_0"] == before - 2 and node["mat_0_0"] == 0
        deposit["mat_0_0"] = 0
        with pytest.raises(ValueError, match="исчерпан"):
            perform(e, "gather", {"material": "mat_0_0", "quantity": 1})


def test_unconscious_resident_still_needs_food_and_can_die_of_starvation():
    from rpg_vkr.domain.society import day

    s = started(unconscious=True)
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=0), {})
        w = e.state["living_world"]
        w["society"]["people"]["watcher"]["civilian"] = True
        resident = w["residents"]["watcher"]
        resident.update(food=0, hunger=9)
        for stock in w["stocks"].values():
            stock["food"] = 0
        for id, p in w["society"]["people"].items():
            if id != "watcher":
                p["civilian"] = False
        e.state["minute"] = 1440
        day(e, 1)
        assert resident["hunger"] == 10 and e.actors["watcher"].state["life"] == "dead"
