"""Real physical NPC inventory, production, access and frozen old-world replay."""

import json
from dataclasses import asdict, replace
from pathlib import Path

from test_catalog_campaign import act

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.domain.society import _tool
from rpg_vkr.unified_session import context
from scripts.rehearse_class_campaign import genesis


def test_registered_smith_tools_drive_real_funded_production_and_wear(tmp_path):
    s = genesis("artisan", 17)
    assert s.gameplay["world_policy"] == 4
    item = next(i for i in s.gameplay["items"] if i["id"] == "smith_tools")
    assert item["source"] == "smith_tools" and item["owner"] == "smith"
    condition = item["durability"]
    before = sum(
        i["quantity"] for i in s.gameplay["items"] if i["owner"] == "smith" and i.get("ammunition")
    )
    act(s, "wait", minutes=1440)
    assert (
        sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i["owner"] == "smith" and i.get("ammunition")
        )
        > before
    )
    item = next(i for i in s.gameplay["items"] if i["id"] == "smith_tools")
    assert item["durability"] < condition
    physical = next(a for a in s.catalog.entities if a.id == item["id"])
    assert physical.state["condition"] == item["durability"]
    assert any(
        r["kind"] == "workshop_product" and r.get("actor") == "smith" and r.get("inputs")
        for r in s.gameplay["living_world"]["society"]["ledger"]
    )
    for _ in range(3):
        act(s, "wait", minutes=0)
    assert sum(i["id"] == "smith_tools" for i in s.gameplay["items"]) == 1
    restored = Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == s.dice.checkpoint()
    from rpg_vkr.storage.campaigns import CampaignRepository
    from rpg_vkr.storage.slots import SaveSlots

    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, s)
    assert slots.load(1).to_dict() == s.to_dict()
    repo = CampaignRepository(tmp_path / "campaigns.sqlite3")
    repo.sync(s)
    assert repo.load(repo.identity(s)).to_dict() == s.to_dict()


def test_tools_left_at_another_place_cannot_work_from_a_distance():
    s = genesis("artisan", 17)
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=17), {})
        assert _tool(e, "smith") is not None
        e.things["smith_tools"] = replace(e.things["smith_tools"], holder="path")
        e.actors["smith_tools"] = replace(e.actors["smith_tools"], parent_id="path")
        assert _tool(e, "smith") is None


def test_old_writer_with_physical_npc_tools_retains_original_outcomes():
    p = Path("docs/validation/final-campaign-2026-10-28/published-world3-tools-save.json")
    saved = json.loads(p.read_bytes())
    s = Session.from_dict(saved["session"], version=31)
    assert json.loads(json.dumps(s.to_dict())) == saved["session"]
    assert "world_policy" not in s.gameplay
    assert not any(i["id"] == "smith_tools" for i in s.gameplay["items"])
    result = asdict(s.dice.roll("1d100", reason="compatibility continuation"))
    result["individual_rolls"] = list(result["individual_rolls"])
    assert result == saved["next_d100"]


def test_world_generation_receives_the_supported_profession_and_real_item_contract(
    qt_app, monkeypatch
):
    from rpg_vkr.narrative.context import build_frame
    from rpg_vkr.narrative.master import campaign_context
    from rpg_vkr.narrative.ollama import OllamaClient

    s = genesis("artisan", 17)
    client = OllamaClient()
    calls = []
    monkeypatch.setattr(client, "_start", lambda *args: calls.append(args))
    client.generate_world(build_frame(s), "fixture:offline", campaign_context(s))
    prompt = calls[0][2]["messages"][0]["content"]
    assert "properties.class: smith" in prompt and "house_0_0" in prompt
    assert "owner_id=тот же ID" in prompt and "party_ally=true" in prompt


def test_an_appointed_child_does_not_start_adult_work(monkeypatch):
    from rpg_vkr.domain import society

    s = genesis("artisan", 17)
    with content.using(3):
        e = Engine(s.gameplay, context(s), DiceRoller(seed=17), {})
        w = e.state["living_world"]
        w["stocks"]["pier"]["food"] = 20
        for day in (90, 180):
            e.state["minute"] = day * 1440
            w["day"] = day
            society.demographics(e, day)
        row = next(
            r for r in content.load().values() if r.get("op") == "office" and r["threshold"] == 4
        )
        assert society.apply_event(e, row, "pier")
        appointed = [
            id
            for id, p in w["society"]["people"].items()
            if not p["mature"] and w["residents"][id]["job"] == "farmer"
        ]
        assert appointed
        worked = []
        original = society.livelihood

        def record(engine, id, place):
            worked.append(id)
            return original(engine, id, place)

        monkeypatch.setattr(society, "livelihood", record)
        e.state["minute"] = 181 * 1440
        society.day(e, 181)
        assert worked and not set(appointed) & set(worked)
