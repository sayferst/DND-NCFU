"""Same execution contracts for the new release, with explicit controlled endgame fixtures."""

import json
import os

import pytest
import test_full_game_catalog as original

from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.domain.dice import DiceRoller

with content.using(2):
    IDS = list(content.load())
VERIFIED = set()


@pytest.fixture(scope="session", autouse=True)
def revision_two_proof():
    yield
    path = os.environ.get("DND_CONTENT_V2_REPORT")
    if path:
        with content.using(2), open(path, "x", encoding="utf-8") as stream:
            json.dump(
                {
                    "catalog_sha256": content.digest(),
                    "tested_ids": sorted(VERIFIED),
                    "method": "controlled_endgame_execution_not_campaign_progression",
                },
                stream,
                ensure_ascii=False,
                indent=2,
            )


@pytest.mark.parametrize("id", IDS, ids=IDS)
def test_revision_two_record_executes(id, monkeypatch):
    prepare = original.fixture_state

    def fixture(class_id="mage"):
        state, ctx = prepare(class_id)
        state.update(catalog_revision=2, catalog_hash=content.digest())
        return state, ctx

    with content.using(2):
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
        else:
            original.test_each_catalog_element_has_a_real_execution_path(id)
        VERIFIED.add(id)
