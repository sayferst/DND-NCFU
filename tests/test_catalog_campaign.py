"""Public Session integration; no assignment to XP or RNG after world genesis."""

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from test_adventure import world_value

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as catalog
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.domain.unified import CLASSES, level
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import MAX_SAVE_BYTES, SaveSlots
from rpg_vkr.unified_session import UnifiedSession


def started(class_id="artisan", *, supplies=False, seed=17):
    s = UnifiedSession.create(
        Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True))),
        class_id,
        CLASSES[class_id][4],
        seed=seed,
        content_revision=2,
    )
    v = world_value()
    v["title"] = "Поселение мастерских"
    for d in v["definitions"]:
        if d["id"] == "seller_type":
            d["properties"].update(
                can_trade=True,
                faction_id="workshop_guild",
                faction_goal="prosperity",
                faction_name="Гильдия мастерских",
            )
    for entity in v["entities"]:
        if entity["id"] == "seller":
            entity["state"]["gold_cp"] = 200000
    for kind in ("forge", "alchemy", "workbench"):
        v["definitions"].append(
            {
                "id": "public_" + kind,
                "name": "Общее рабочее место " + kind,
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"station": kind, "public": True},
            }
        )
        v["entities"].append(
            {"id": "place_" + kind, "definition_id": "public_" + kind, "parent_id": "pier"}
        )
    if supplies:
        # Authored test-town warehouse: finite start goods, no runtime resource/XP injection.
        for row in catalog.available("material"):
            if row["process"]:
                continue
            v["definitions"].append(
                {
                    "id": "supply_" + row["id"],
                    "name": row["name"],
                    "kind": "material",
                    "categories": ["materials"],
                    "price_cp": row["price_cp"],
                    "properties": {"game_template_id": row["id"], "portable": True},
                }
            )
            v["entities"].append(
                {
                    "id": "stock_" + row["id"],
                    "definition_id": "supply_" + row["id"],
                    "parent_id": "hero",
                    "owner_id": "hero",
                    "quantity": 400,
                }
            )
        row = catalog.row("house_0_0")
        v["definitions"].append(
            {
                "id": "spare_tools",
                "name": "Запасные инструменты",
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"game_template_id": row["id"], "durability": row["durability"]},
            }
        )
        for n in range(3):
            v["entities"].append(
                {
                    "id": f"spare_{n}",
                    "definition_id": "spare_tools",
                    "parent_id": "hero",
                    "owner_id": "hero",
                }
            )
    s.start_world(build_world(v, s, "authored-integration-town"))
    # Genesis goods become real carried engine items; no fixture state patch.
    return s


def act(s, command, **args):
    return s.perform_gameplay(command, args, s._request_token())


def test_schema31_atomicity_receipt_replay_and_physical_stock(tmp_path):
    s = started("mage")
    stock = next(
        i for i in s.gameplay["items"] if i["owner"] == "seller" and i.get("template") == "mat_2_0"
    )
    before_qty = stock["quantity"]
    before_money = s.gameplay["copper"]
    act(s, "buy", merchant="seller", item=stock["id"])
    assert (
        next(i for i in s.gameplay["items"] if i["id"] == stock["id"])["quantity"] == before_qty - 1
    )
    assert s.gameplay["copper"] < before_money
    act(s, "cast", spell="light", target="hero")
    assert receipt(s)["committed"] and s.gameplay["statuses"]["hero"]
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        act(s, "cast", spell="bolt", target="missing")
    assert (s.to_dict(), s.dice.checkpoint()) == before
    act(s, "wait", minutes=1440)
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, s)
    restored = slots.load(1)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == s.dice.checkpoint()
    repo = CampaignRepository(tmp_path / "world.db")
    repo.sync(s)
    assert repo.load(repo.identity(s)).to_dict() == s.to_dict()
    damaged = deepcopy(s.to_dict())
    damaged["snapshot"]["gameplay"]["state"]["xp"] += 1
    with pytest.raises(ValueError):
        Session.from_dict(damaged, version=31)
    assert "secret" not in json.dumps(
        __import__("rpg_vkr.narrative.master", fromlist=["campaign_context"]).campaign_context(s),
        ensure_ascii=False,
    )


def test_public_progression_one_to_twenty(tmp_path):
    if not os.environ.get("DND_LONG_CAMPAIGN"):
        pytest.skip("Run explicitly: DND_LONG_CAMPAIGN=1; expensive 1-to-20 replay")
    s = started(supplies=True)
    # Genesis supplies remain finite; every subsequent change uses public Session actions.
    milestones = [{"level": 1, "turn": 0, "xp": 0}]
    outputs = [r for r in catalog.load().values() if r["kind"] in ("weapon", "armour", "household")]
    outputs.sort(key=lambda r: (r["level"], r["id"]))
    attempts = 0

    def learn(recipe):
        if recipe["id"] not in s.gameplay["known_recipes"]:
            for _ in range(12):
                act(s, "research", entry=recipe["id"])
                if recipe["id"] in s.gameplay["known_recipes"]:
                    return
            raise AssertionError("Learning did not succeed")

    def count(id):
        return sum(
            i["quantity"]
            for i in s.gameplay["items"]
            if i.get("template") == id and i["owner"] == "hero"
        )

    def prepare(recipe):
        learn(recipe)
        for key, n in recipe["ingredients"].items():
            while count(key) < n:
                parent = next(r for r in catalog.available("recipe") if key in r["outputs"])
                prepare(parent)
                act(s, "manufacture", recipe=parent["id"], result=key)
        tools = [
            i
            for i in s.gameplay["items"]
            if i["owner"] == "hero"
            and i["durability"] > 0
            and catalog.row(i.get("template", "house_0_0")).get("capability") == "tools"
        ]
        if sum(i["durability"] for i in tools) < 4:
            act(s, "manufacture", recipe="recipe_production_0_0", result="house_0_0")

    for row in outputs:
        if level(s.gameplay["xp"]) == 20:
            break
        if row["level"] > level(s.gameplay["xp"]):
            continue
        recipe = next(r for r in catalog.available("recipe") if row["id"] in r["outputs"])
        for _ in range(20):
            attempts += 1
            prepare(recipe)
            act(s, "manufacture", recipe=recipe["id"], result=row["id"])
            made = next(
                (
                    i
                    for i in s.gameplay["items"]
                    if i.get("template") == row["id"]
                    and i.get("made_by") == "hero"
                    and i["owner"] == "hero"
                ),
                None,
            )
            if made:
                break
        assert made
        for _retry in range(32):
            merchant = next(e for e in s.catalog.entities if e.id == "seller")
            remaining = (merchant.state or {}).get("closed_until", 0) - s.gameplay["minute"]
            if remaining > 0:
                act(s, "wait", minutes=min(1440, remaining))
                continue
            if not s.actor_is_here("seller"):
                act(s, "wait", minutes=60)
                continue
            act(s, "sell", merchant="seller", item=made["id"])
            break
        else:
            raise AssertionError("Town did not reopen")
        lv = level(s.gameplay["xp"])
        if lv > milestones[-1]["level"]:
            milestones.append({"level": lv, "turn": len(s.turns), "xp": s.gameplay["xp"]})
        while 2 * sum(lv >= n for n in (4, 8, 12, 16, 20)) > sum(
            s.gameplay["ability_increases"].values()
        ):
            ability = "intelligence" if s.effective_character.intelligence < 20 else "constitution"
            act(s, "raise", ability=ability)
    assert level(s.gameplay["xp"]) == 20
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, s)
    size = (tmp_path / "saves/slot-1.json").stat().st_size
    assert size < MAX_SAVE_BYTES
    r = slots.load(1)
    assert r.to_dict() == s.to_dict() and r.dice.checkpoint() == s.dice.checkpoint()
    report = {
        "scenario": "authored finite warehouse artisan trade hub; no XP/level injection",
        "milestones": milestones,
        "turns": len(s.turns),
        "manufacture_attempts": attempts,
        "days": s.gameplay["minute"] // 1440,
        "save_bytes": size,
        "replay": True,
        "not_manual_gameplay": True,
    }
    path = os.environ.get("DND_CAMPAIGN_REPORT")
    if path:
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
