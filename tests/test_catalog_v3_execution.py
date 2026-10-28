"""Same execution contracts for the new release, with explicit controlled endgame fixtures."""

import json
import os

import pytest
import test_full_game_catalog as original

from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.dice import DiceRoller

with content.using(3):
    IDS = list(content.load())
VERIFIED = set()


@pytest.fixture(scope="session", autouse=True)
def revision_three_proof():
    yield
    path = os.environ.get("DND_CONTENT_V3_REPORT")
    if path:
        with content.using(3), open(path, "x", encoding="utf-8") as stream:
            json.dump(
                {
                    "catalog_sha256": content.digest(),
                    "world_policy": 4,
                    "tested_ids": sorted(VERIFIED),
                    "method": "controlled_endgame_execution_not_campaign_progression",
                },
                stream,
                ensure_ascii=False,
                indent=2,
            )


@pytest.mark.parametrize("id", IDS, ids=IDS)
def test_revision_three_record_executes(id, monkeypatch):
    prepare = original.fixture_state

    def fixture(class_id="mage"):
        state, ctx = prepare(class_id)
        state.update(catalog_revision=3, catalog_hash=content.digest(), world_policy=4)
        state.update(contracts={}, activity={"gathered": {}, "crafted": {}, "visited": {}})
        return state, ctx

    with content.using(3):
        monkeypatch.setattr(original, "fixture_state", fixture)
        row = content.row(id)
        if row["kind"] == "recipe" and row["category"] == "repair":
            state, ctx = fixture("artisan")
            engine = Engine(state, ctx, DiceRoller(seed=0), {})
            base = row["compatible_material"]
            target = next(
                r
                for r in content.load().values()
                if r["kind"] in ("weapon", "armour", "household")
                and content.row(r["material"])["base"] == base
            )
            item = engine.add_item(target["id"])
            item["durability"] = 1
            ready = engine.finish()
            result = original.run(
                ready["state"],
                ctx | {k: ready[k] for k in ("world", "catalog", "scene")},
                "repair",
                {"recipe": id, "item": item["id"]},
            )
            assert (
                next(i for i in result["state"]["items"] if i["id"] == item["id"])["durability"] > 1
            )
        elif row["kind"] == "event":
            from copy import deepcopy

            from rpg_vkr.domain.catalog_world import apply_event

            state, ctx = fixture("mage")
            engine = Engine(state, ctx, DiceRoller(seed=0), {})
            for actor_id, resident in engine.state["living_world"]["residents"].items():
                resident["job"] = "resident"
                resident["knowledge"] = ["observed_" + actor_id]
                engine.state["living_world"]["society"]["people"][actor_id]["civilian"] = True
            from rpg_vkr.domain.society import emit

            emit(engine, "resource_observed", engine.scene.current, resource=row["resource"])
            if row["op"] in ("gossip", "exchange_news"):
                people = sorted(engine.refs)
                recipient = people[(row["role"] + 1) % len(people)]
                engine.state["living_world"]["residents"][recipient]["knowledge"] = []
            before = deepcopy(engine.state["living_world"])
            assert apply_event(engine, row)
            assert engine.state["living_world"] != before
            assert any(
                r.get("template") == id for r in engine.state["living_world"]["society"]["ledger"]
            )
            assert all(
                n >= 0 for s in engine.state["living_world"]["stocks"].values() for n in s.values()
            )
        else:
            original.test_each_catalog_element_has_a_real_execution_path(id)
        VERIFIED.add(id)
