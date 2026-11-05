"""Consumables and reading use actual inventory, life, clocks and replay."""

from dataclasses import replace

import pytest
from test_library_magic_runtime import take
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.model import ROOT, read_jsonl
from rpg_vkr.world_library.store import Library
from rpg_vkr.world_library.utility_rules import compile_utility, perform, validate


@pytest.fixture
def library(tmp_path):
    lib = Library.sqlite(tmp_path / "library.sqlite3")
    lib.migrate()
    lib.import_records(read_jsonl(ROOT / "data/world_library/seed-v1.jsonl"))
    yield lib
    lib.close()


def spawn(session, library, profile, id):
    record = next(r for r in library.all() if r["profile"] == profile)
    commit(session, preview(library, session, record["id"], id))
    take(session, id)
    return record


def test_all_320_original_utilities_have_closed_programs():
    count = 0
    for row in read_jsonl(ROOT / "data/world_library/seed-v1.jsonl"):
        if row["profile"] in {"food", "medicine", "poison", "book", "quest"}:
            validate(compile_utility(row))
            count += 1
    assert count == 320


def test_medicine_consumes_one_real_item_and_heals_without_rng(library):
    s = campaign(hp=3)
    row = spawn(s, library, "medicine", "dressing")
    rng = s.dice.checkpoint()
    before = next(e for e in s.catalog.entities if e.id == "wounded").state["hp"]
    s.perform_gameplay("library_use", {"item": "dressing", "target": "wounded"}, "heal-library")
    after = next(e for e in s.catalog.entities if e.id == "wounded").state["hp"]
    assert after == min(12, before + 2 * row["attributes"]["potency"])
    assert not any(e.id == "dressing" for e in s.catalog.entities)
    assert s.dice.checkpoint() == rng
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_food_is_consumed_and_nutrition_survives_replay(library):
    s = campaign(hp=12)
    spawn(s, library, "food", "ration")
    s.perform_gameplay("library_use", {"item": "ration"}, "eat-library")
    assert s.gameplay["library_nutrition"]["satiated_until"] > s.gameplay["minute"]
    assert not any(e.id == "ration" for e in s.catalog.entities)
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_spoiled_food_and_dead_patient_do_not_spend_items(library):
    s = campaign(hp=12)
    row = spawn(s, library, "food", "ration")
    e = Engine(s.gameplay, context(s), s.dice, {})
    e.state["minute"] += row["attributes"]["shelf_days"] * 1440
    before = e.owned("ration")["quantity"]
    with pytest.raises(ValueError, match="spoiled"):
        perform(e, {"item": "ration"})
    assert e.owned("ration")["quantity"] == before

    spawn(s, library, "medicine", "medicine")
    e = Engine(s.gameplay, context(s), s.dice, {})
    target = e.actors["wounded"]
    e.actors[target.id] = replace(target, state={"hp": 0, "life": "dead"})
    with pytest.raises(ValueError, match="dead"):
        perform(e, {"item": "medicine", "target": "wounded"})
    assert e.owned("medicine")["quantity"] == 1


def test_book_and_quest_record_knowledge_without_granting_money_or_xp(library):
    s = campaign(hp=12)
    for profile in ("book", "quest"):
        row = spawn(s, library, profile, profile)
        copper, xp = s.gameplay["copper"], s.gameplay["xp"]
        s.perform_gameplay("library_use", {"item": profile}, "read-" + profile)
        assert row["id"] in s.gameplay["library_knowledge"]
        assert s.gameplay["copper"] == copper and s.gameplay["xp"] == xp
        assert any(e.id == profile for e in s.catalog.entities)
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_failed_poison_delivery_still_consumes_item(library, monkeypatch):
    s = campaign(hp=12)
    spawn(s, library, "poison", "powder")
    e = Engine(s.gameplay, context(s), s.dice, {})
    e.state["battle"] = {"sides": {"hero": "party", "wounded": "enemy"}}
    monkeypatch.setattr(e, "check", lambda *args: False)
    before = e.hp("wounded")
    perform(e, {"item": "powder", "target": "wounded"})
    assert e.hp("wounded") == before and "powder" not in e.actors
