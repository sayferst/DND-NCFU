"""Every data record executes in controlled domain fixtures; campaign tests are separate."""

import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from test_adventure import world_value

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as catalog
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.catalog_engine import Engine, execute
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.dice import DiceRoller
from rpg_vkr.domain.unified import CLASSES, caps
from rpg_vkr.unified_session import UnifiedSession, context

VERIFIED = set()


@pytest.fixture(scope="session", autouse=True)
def content_proof():
    yield
    path = os.environ.get("DND_CONTENT_REPORT")
    if path:
        with Path(path).open("x", encoding="utf-8") as f:
            json.dump(
                {
                    "catalog_sha256": catalog.digest(),
                    "tested_ids": sorted(VERIFIED),
                    "method": "actual_catalog_engine_in_controlled_domain_fixtures",
                    "not_a_claim_of_level20_playthrough": True,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )


@lru_cache(maxsize=6)
def scenario(class_id="mage"):
    scores = dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True))
    session = UnifiedSession.create(
        Character(**scores), class_id, CLASSES[class_id][4], seed=0, content_revision=2
    )
    value = world_value()
    for entry in value["entities"]:
        if entry["definition_id"] in ("seller_type", "watcher_type"):
            entry["parent_id"] = value["start"]
            entry.setdefault("state", {}).update(hp=3, mp=20, st=20, gold_cp=10000)
    for kind in ("forge", "alchemy", "workbench"):
        value["definitions"].append(
            {
                "id": "test_" + kind,
                "name": "Рабочее место " + kind,
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"station": kind, "public": True},
            }
        )
        value["entities"].append(
            {"id": "station_" + kind, "definition_id": "test_" + kind, "parent_id": value["start"]}
        )
    session.start_world(build_world(value, session, "catalog-domain-fixture"))
    state = session.gameplay
    # Controlled endgame resources, not a fabricated campaign or training receipt.
    state["xp"] = 19000
    state["spells"] = [r["id"] for r in catalog.available("spell")]
    state["known_recipes"] = [r["id"] for r in catalog.available("recipe")]
    state["talents"] += [r["id"] for r in catalog.available("talent", category=class_id)]
    limits = caps(state, session.character)
    state.update(
        mp_cap=limits["mp"], mp=max(0, limits["mp"] - 20), st_cap=limits["st"], st=limits["st"]
    )
    ctx = context(session)
    ctx["world"].update(max_hp=limits["hp"], hp=limits["hp"] // 2)
    # Controlled level-20 equipment prerequisites; separate from public progression test.
    ctx["character"].update(strength=20, dexterity=20)
    e = Engine(state, ctx, DiceRoller(seed=0), {})
    for row in catalog.available("material"):
        e.add_item(row["id"], 2000)
    e.add_item("house_3_0")
    ready = e.finish()
    return ready["state"], ctx | {k: ready[k] for k in ("world", "catalog", "scene")}


def fixture_state(class_id="mage"):
    state, ctx = scenario(class_id)
    return deepcopy(state), deepcopy(ctx)


def run(state, ctx, command, args):
    return execute(state, command, args, ctx, DiceRoller(seed=0))


@pytest.mark.parametrize("id", list(catalog.load()), ids=list(catalog.load()))
def test_each_catalog_element_has_a_real_execution_path(id):
    row = catalog.row(id)
    kind = row["kind"]
    class_id = (
        row["class_id"]
        if kind == "talent"
        else "artisan"
        if kind in ("recipe", "material", "household", "weapon", "armour")
        else "mage"
    )
    state, ctx = fixture_state(class_id)
    if kind in ("spell", "talent"):
        primary = row["effects"][0]["op"]
        target = "watcher" if primary in ("damage", "drain_mp", "revive") else "hero"
        if primary == "revive":
            for entity in ctx["catalog"]["entities"]:
                if entity["id"] == target:
                    entity["state"]["hp"] = 0
        args = {"spell" if kind == "spell" else "talent": id, "target": target}
        if primary in ("repair", "appraise"):
            item = next(i for i in state["items"] if i["id"] == state["weapon"])
            item["durability"] = 1
            args["item"] = item["id"]
        if primary == "travel":
            args["destination"] = "path"
        result = run(state, ctx, "cast" if kind == "spell" else "ability", args)
        if row["mode"] in ("delayed", "sustained"):
            next_context = ctx | {k: result[k] for k in ("world", "catalog", "scene")}
            result = run(result["state"], next_context, "wait", {"minutes": 30})
            assert not result["state"]["pending"]
        assert result["state"]["mp"] >= 0 and result["state"]["st"] >= 0
    elif kind == "consumable":
        engine = Engine(state, ctx, DiceRoller(seed=0), {})
        item = engine.add_item(id)
        before_quantity = item["quantity"]
        if row["category"] == "ammunition":
            bow = engine.add_item("gear_longbow_0_0")
            engine.state["weapon"] = bow["id"]
            engine.state["items"] = [
                i for i in engine.state["items"] if not i.get("ammunition") or i["id"] == item["id"]
            ]
            engine.state["battle"] = {
                "order": ["hero", "watcher"],
                "sides": {"hero": "party", "watcher": "enemy"},
                "round": 1,
            }
            ready = engine.finish()
            args = {"target": "watcher"}
            command = "attack"
        else:
            ready = engine.finish()
            command = "consume"
            primary = row.get("effects", [])[0]["op"]
            args = {
                "item": item["id"],
                "target": "watcher"
                if row["category"] == "scrolls" or primary == "revive"
                else "hero",
            }
            if primary == "revive":
                for entity in ready["catalog"]["entities"]:
                    if entity["id"] == "watcher":
                        entity["state"]["hp"] = 0
        result = run(
            ready["state"],
            ctx | {k: ready[k] for k in ("world", "catalog", "scene")},
            command,
            args,
        )
        assert (
            sum(i["quantity"] for i in result["state"]["items"] if i["id"] == item["id"])
            == before_quantity - 1
        )
    elif kind in ("recipe", "material", "household", "weapon", "armour"):
        if kind == "material" and row["process"] == 0:
            result = run(state, ctx, "gather", {"material": id, "quantity": 1})
            assert (
                result["state"]["living_world"]["nodes"]["pier"][id]
                == state["living_world"]["nodes"]["pier"][id] - 1
            )
        elif kind == "recipe" and row["category"] == "repair":
            engine = Engine(state, ctx, DiceRoller(seed=0), {})
            item = engine.add_item(f"gear_sword_{row['compatible_material']}_0")
            item["durability"] = 1
            ready = engine.finish()
            result = run(
                ready["state"],
                ctx | {k: ready[k] for k in ("world", "catalog", "scene")},
                "repair",
                {"recipe": id, "item": item["id"]},
            )
            assert (
                next(i for i in result["state"]["items"] if i["id"] == item["id"])["durability"] > 1
            )
        else:
            recipe = (
                row
                if kind == "recipe"
                else next(r for r in catalog.available("recipe") if id in r["outputs"])
            )
            output = recipe["outputs"][0] if kind == "recipe" else id
            old = sum(i.get("quantity", 1) for i in state["items"] if i.get("template") == output)
            result = run(state, ctx, "manufacture", {"recipe": recipe["id"], "result": output})
            assert (
                sum(
                    i.get("quantity", 1)
                    for i in result["state"]["items"]
                    if i.get("template") == output
                )
                > old
            )
            assert any(
                d["properties"].get("game_template_id") == output
                for d in result["catalog"]["definitions"]
            )
        if kind in ("weapon", "armour", "household"):
            next_context = ctx | {k: result[k] for k in ("world", "catalog", "scene")}
            made = next(
                i
                for i in result["state"]["items"]
                if i.get("template") == id and i["owner"] == "hero" and i.get("made_by") == "hero"
            )
            if kind == "household":
                result = run(
                    result["state"], next_context, "consume", {"item": made["id"], "target": "hero"}
                )
                assert any(e["kind"] == "equipment_used" for e in result["battle_events"])
            else:
                result = run(result["state"], next_context, "equip", {"item": made["id"]})
                ready = ctx | {k: result[k] for k in ("world", "catalog", "scene")}
                engine = Engine(result["state"], ready, DiceRoller(seed=0), {})
                if kind == "weapon":
                    if row["category"] in ("longbow", "crossbow"):
                        engine.add_item("use_ammunition_0_0")
                    engine.state["battle"] = {
                        "order": ["hero", "watcher"],
                        "sides": {"hero": "party", "watcher": "enemy"},
                        "round": 1,
                    }
                    from rpg_vkr.domain.catalog_actions_v2 import hit

                    hit(engine, "hero", "watcher")
                    assert (
                        engine.attacks
                        and next(i for i in engine.state["items"] if i["id"] == made["id"])[
                            "durability"
                        ]
                        == made["durability"] - 1
                    )
                else:
                    before = engine.world.hp
                    assert engine.defence("hero") >= 10
                    engine.damage("hero", 6, row["resistance"])
                    assert engine.world.hp >= before - 5
                result = engine.finish()
    elif kind == "creature":
        from rpg_vkr.domain.catalog_actions_v2 import npc_round
        from rpg_vkr.domain.catalog_world import spawn_creature

        engine = Engine(state, ctx, DiceRoller(seed=0), {})
        actor_id = spawn_creature(engine, row, "unit-encounter")
        if row["behavior"] in ("healer", "scavenger", "skirmisher"):
            engine.change_hp(actor_id, 1 - engine.hp(actor_id))
        engine.state["battle"] = {
            "order": ["hero", actor_id],
            "sides": {"hero": "party", actor_id: "enemy"},
            "round": 1,
        }
        before_hp = engine.world.hp
        npc_round(engine, "recover")
        assert (
            engine.attacks or engine.events or engine.state["statuses"] or engine.hp(actor_id) > 1
        )
        result = engine.finish()
        assert any(a["id"] == actor_id for a in result["catalog"]["entities"])
        assert result["world"]["hp"] <= before_hp
    elif kind == "event":
        from rpg_vkr.domain.catalog_world import apply_event

        engine = Engine(state, ctx, DiceRoller(seed=0), {})
        for actor_id, resident in engine.state["living_world"]["residents"].items():
            resident["job"] = "resident"
            resident["knowledge"] = ["observed_" + actor_id]
        old = json.dumps(
            {
                "world": engine.state["living_world"],
                "actors": [a.to_dict() for a in engine.actors.values()],
            },
            sort_keys=True,
        )
        assert apply_event(engine, row)
        new = json.dumps(
            {
                "world": engine.state["living_world"],
                "actors": [a.to_dict() for a in engine.actors.values()],
            },
            sort_keys=True,
        )
        assert old != new
        assert engine.state["world_log"][-1]["id"] == id
        result = engine.finish()
    else:
        raise AssertionError("Category without an execution test: " + kind)
    VERIFIED.add(id)


def test_published_campaign30_replays_without_new_content():
    path = Path("docs/validation/full-system-2026-10-27/campaign30-before.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    session = Session.from_dict(data["session"], version=30)
    assert (
        session.schema_version == 30
        and json.loads(json.dumps(session.to_dict())) == data["session"]
    )
    assert "content_revision" not in session.gameplay
