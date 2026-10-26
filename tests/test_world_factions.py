"""Playable revision three: real NPCs, conserved faction funds, public knowledge/replay."""

import json
from copy import deepcopy

import pytest
from test_adventure import world_value
from test_gameplay_integration import hero as first_hero

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.storage.knowledge import export_session, restore_session
from rpg_vkr.storage.slots import SaveSlots


def hero(*, declared=True, gossip=False):
    old = first_hero(profile="warrior")
    session = Session.create_hero(old.character, "fighter", seed=13)
    session.enable_gameplay(old.gameplay["identity"], revision=3)
    value = world_value()
    if declared:
        value["definitions"][0]["properties"].update(
            faction_id="guild", faction_name="Мастера", faction_goal="prosperity"
        )
        value["definitions"].append(
            {
                "id": "warden_type",
                "name": "Дозорный",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {
                    "hp_max": 20,
                    "faction_id": "guard",
                    "faction_name": "Стража",
                    "faction_goal": "security",
                },
            }
        )
        value["entities"].append(
            {"id": "warden", "definition_id": "warden_type", "parent_id": "pier"}
        )
    if gossip:
        value["entities"][0]["parent_id"] = "path"
        value["definitions"].append(
            {
                "id": "tiny_type",
                "name": "Разбойник",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {"hp_max": 1, "defence": 1},
            }
        )
        value["entities"].append({"id": "tiny", "definition_id": "tiny_type", "parent_id": "pier"})
    session.start_world(build_world(value, session, "synthetic-model"))
    return session


def perform(session, command, **args):
    return session.perform_gameplay(command, args, "test_" + str(len(session.turns)))


def coins(session):
    return session.world.gold * 100 + session.gameplay["copper"]


def roundtrip(session):
    raw = session.to_dict()
    restored = Session.from_dict(deepcopy(raw))
    assert restored.schema_version == 26
    assert restored.to_dict() == raw
    assert restored.dice.roll_d20() == session.dice.roll_d20()


def test_declared_factions_known_only_at_contact_and_no_forced_group():
    session = hero()
    state = session.gameplay
    assert set(state["known_factions"]) == {"guard", "guild"}
    assert state["factions_v3"]["guard"]["members"] == ["warden"]
    assert all(f["treasury_cp"] == 1000 for f in state["factions_v3"].values())
    assert not hero(declared=False).gameplay["factions_v3"]
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    before = session.to_dict()
    with pytest.raises(ValueError, match="представителя"):
        perform(session, "donate", faction="guild", amount_cp=100)
    assert session.to_dict() == before
    roundtrip(session)


def test_donation_transfers_money_reputation_and_is_idempotent():
    session = hero()
    before = coins(session)
    turn = session.perform_gameplay("donate", {"faction": "guild", "amount_cp": 157}, "gift")
    assert coins(session) == before - 157
    assert session.gameplay["factions_v3"]["guild"]["treasury_cp"] == 1157
    assert session.gameplay["known_factions"]["guild"]["reputation"] == 1
    assert session.d20_progress.xp == 0
    saved = session.to_dict()
    assert (
        session.perform_gameplay("donate", {"faction": "guild", "amount_cp": 157}, "gift") == turn
    )
    assert session.to_dict() == saved
    roundtrip(session)


@pytest.mark.parametrize(
    "args",
    [
        {"faction": "guild", "amount_cp": 10000},
        {"faction": "unknown", "amount_cp": 1},
        {"faction": "guild", "amount_cp": True},
        {"faction": "guild", "amount_cp": -1},
        {"faction": [], "amount_cp": 1},
    ],
)
def test_invalid_donation_rolls_back_everything(args):
    session = hero()
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.perform_gameplay("donate", args, "rejected")
    assert session.to_dict() == before and session.dice.checkpoint() == rng


def test_daily_projects_move_real_npc_spend_finite_funds_and_do_not_give_player_items():
    session = hero()
    before, money = len(session.interaction_state().things), coins(session)
    perform(session, "wait", minutes=3 * 1440)
    state = session.gameplay
    assert state["factions_v3"]["guard"]["treasury_cp"] == 640
    assert state["factions_v3"]["guard"]["influence"] == 16
    assert state["factions_v3"]["guild"]["treasury_cp"] == 700
    assert (
        next(a for a in session.interaction_state().actor_refs if a.id == "warden").place == "path"
    )
    assert coins(session) == money and len(session.interaction_state().things) == before
    for _ in range(3):
        perform(session, "wait", minutes=7 * 1440)
    for faction in session.gameplay["factions_v3"].values():
        assert faction["treasury_cp"] >= 0
        assert faction["treasury_cp"] + faction["spent_cp"] == 1000
    roundtrip(session)


def test_stronger_patrols_collect_quoted_duty_without_creating_money():
    session = hero()
    perform(session, "wait", minutes=3 * 1440)
    before = session.to_dict()
    quote = session.preview_gameplay(
        "trade_world", {"merchant": "seller", "item": "stock", "operation": "buy", "quantity": 1}
    )
    assert session.to_dict() == before
    receipt = quote["transaction"]
    assert receipt["duty_cp"] == (receipt["base_price_cp"] * 5 + 99) // 100
    money, treasury = coins(session), session.gameplay["factions_v3"]["guard"]["treasury_cp"]
    seller = next(e for e in session.catalog.entities if e.id == "seller").state["gold_cp"]
    session.submit_trade("куплю бинт", "seller", "stock", "buy", 1)
    assert coins(session) == money - receipt["price_cp"]
    assert session.gameplay["factions_v3"]["guard"]["treasury_cp"] == treasury + receipt["duty_cp"]
    assert (
        next(e for e in session.catalog.entities if e.id == "seller").state["gold_cp"]
        == seller + receipt["base_price_cp"]
    )
    roundtrip(session)


def test_public_context_and_ui_never_show_hidden_treasury(qt_app, tmp_path):
    from rpg_vkr.ui.main_window import MainWindow

    session = hero()
    context = campaign_context(session)
    public = json.dumps(context["known_factions"], ensure_ascii=False)
    assert "Стража" in public and "treasury" not in public and "influence" not in public
    window = MainWindow(session=session, saves=SaveSlots(tmp_path))
    window._session = session
    window._refresh_character()
    assert window.faction_choice.count() == 2
    assert "Стража" in window.faction_info.toPlainText()
    assert "1000" not in window.faction_info.toPlainText()
    window.close()


def test_json_sqlite_archive_replay_and_corruption(tmp_path):
    session = hero()
    perform(session, "donate", faction="guard", amount_cp=100)
    perform(session, "wait", minutes=3 * 1440)
    session.submit_trade("куплю бинт", "seller", "stock", "buy", 1)
    slots = SaveSlots(tmp_path / "slots")
    slots.save(1, session)
    assert slots.load(1).to_dict() == session.to_dict()
    export_session(session, tmp_path / "world.sqlite3")
    assert restore_session(tmp_path / "world.sqlite3").to_dict() == session.to_dict()
    from rpg_vkr.storage.campaigns import CampaignRepository

    repo = CampaignRepository(tmp_path / "archive.sqlite3")
    repo.sync(session)
    assert repo.load(repo.identity(session)).to_dict() == session.to_dict()
    for target in ["state", "result"]:
        raw = deepcopy(session.to_dict())
        if target == "state":
            raw["gameplay"]["state"]["factions_v3"]["guard"]["treasury_cp"] += 1
        else:
            raw["turns"][-1]["gameplay"]["result"]["transaction"]["duty_cp"] += 1
        with pytest.raises(ValueError):
            Session.from_dict(raw)
    roundtrip(session)


def test_gossip_transfers_only_confirmed_victory_with_source_and_heard_status():
    session = hero(gossip=True)
    assert "guild" not in session.gameplay["known_factions"]
    for _ in range(8):
        perform(session, "attack", target="tiny", lethal=0)
        if "tiny" in session.gameplay["victories"]:
            break
    assert "tiny" in session.gameplay["victories"]
    witness = session.gameplay["npc"]["warden"]["knowledge"]
    assert any(f["event"] == "tiny" and f["kind"] == "personally_known" for f in witness)
    assert not session.gameplay["npc"].get("seller", {}).get("knowledge")
    perform(session, "wait", minutes=1440)
    heard = session.gameplay["npc"]["seller"]["knowledge"]
    assert heard == [{"event": "tiny", "kind": "heard", "source": "warden", "confidence": 75}]
    assert not session.gameplay["npc"]["watcher"].get("knowledge")
    encoded = json.dumps(session.gameplay["npc"], ensure_ascii=False)
    assert "Код переправы" not in encoded and "янтарная птица" not in encoded
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    public = campaign_context(session)["npc_public_events"]
    assert public["seller"][0]["kind"] == "heard"
    assert "watcher" not in public
    raw = deepcopy(session.to_dict())
    gossip_turn = next(
        t
        for t in raw["turns"]
        if t["gameplay"]
        and any(
            e["kind"] == "information_transferred"
            for e in t["gameplay"]["result"].get("simulation_events", [])
        )
    )
    transfer = next(
        e
        for e in gossip_turn["gameplay"]["result"]["simulation_events"]
        if e["kind"] == "information_transferred"
    )
    transfer["source"] = "invented"
    with pytest.raises(ValueError):
        Session.from_dict(raw)
    roundtrip(session)


def test_unaffordable_duty_rejects_entire_purchase_and_rng():
    session = hero()
    perform(session, "wait", minutes=3 * 1440)
    quote = session.preview_gameplay(
        "trade_world", {"merchant": "seller", "item": "stock", "operation": "buy", "quantity": 1}
    )["transaction"]
    perform(session, "donate", faction="guild", amount_cp=coins(session) - quote["base_price_cp"])
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="пошлину"):
        session.submit_trade("куплю бинт", "seller", "stock", "buy", 1)
    assert session.to_dict() == before and session.dice.checkpoint() == rng
    roundtrip(session)


def test_engaged_actor_is_not_teleported_by_patrol():
    from rpg_vkr.domain.factions import simulate

    session = hero()
    perform(session, "attack", target="warden", lethal=0)
    assert session.gameplay["active"] == "warden"
    state = deepcopy(session.gameplay)
    state["minute"] += 1440
    after, scene, events = simulate(state, session.catalog, session.interaction_state())
    assert next(a for a in scene.actor_refs if a.id == "warden").place == "pier"
    assert after["factions_v3"]["guard"]["treasury_cp"] == 1000
    assert not any(e.get("faction") == "guard" for e in events)
    roundtrip(session)


def test_actual_schema25_fixture_from_frozen_runtime_preserves_bytes_and_rng():
    import hashlib
    from dataclasses import asdict
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    meta = json.loads(
        (
            root / "docs/validation/gameplay-v3-factions-2026-10-26/fixture-v25-source.json"
        ).read_text(encoding="utf-8")
    )
    raw = (root / "tests/fixtures/session-v25-physical.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == meta["fixture_sha256"]
    value = json.loads(raw)
    session = Session.from_dict(value["session"], version=25)
    assert session.schema_version == 25
    assert json.loads(json.dumps(session.to_dict(), ensure_ascii=False)) == value["session"]
    assert asdict(session.dice.roll_d20()) == meta["next_roll"]
    assert meta["source_commit"] == "1f1bd1b"


def test_tutorial_without_declared_factions_remains_playable_and_replays():
    old = first_hero()
    session = Session.create_hero(old.character, "fighter", seed=13)
    session.enable_gameplay(old.gameplay["identity"], revision=3)
    turn = perform(session, "wait", minutes=1440)
    assert not session.gameplay["factions_v3"]
    assert "faction_projects" not in session.gameplay
    assert "Ремесленная община" not in turn.text
    roundtrip(session)


def test_closed_representative_cannot_accept_money():
    session = hero()
    perform(session, "wait", minutes=14 * 60)
    before = session.to_dict()
    with pytest.raises(ValueError, match="представителя"):
        perform(session, "donate", faction="guild", amount_cp=1)
    assert session.to_dict() == before
    roundtrip(session)


def test_quote_shows_duty_and_does_not_commit(qt_app, tmp_path):
    from rpg_vkr.ui.copper_shop import CopperTradeDialog
    from rpg_vkr.ui.main_window import MainWindow

    session = hero()
    perform(session, "wait", minutes=3 * 1440)
    before, rng = session.to_dict(), session.dice.checkpoint()
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "slots"))
    dialog = CopperTradeDialog(window, "seller")
    assert "пошлина 5%" in dialog.status.text()
    assert "Итог" in dialog.status.text()
    assert session.to_dict() == before and session.dice.checkpoint() == rng
    dialog.close()
    window.close()
