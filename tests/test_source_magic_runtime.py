"""MP-adapted source spell IDs create actual formulas, spend MP and replay."""

import sqlite3
from copy import deepcopy

import pytest
from test_library_magic_runtime import take
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.world_library.bridge import commit, is_descriptive, preview
from rpg_vkr.world_library.model import ROOT, read_jsonl
from rpg_vkr.world_library.source_magic_rules import mp_cost, validate
from rpg_vkr.world_library.store import Library


@pytest.fixture(scope="module")
def library():
    db = Library(sqlite3.connect(":memory:"))
    db.execute("PRAGMA foreign_keys=ON")
    db.migrate()
    rows = [
        r
        for r in read_jsonl(ROOT / "data/world_library/rpgd100-reference-index.jsonl")
        if r["attributes"].get("source_spell_v1")
    ]
    assert len(rows) == 2
    db.import_records(rows)
    yield db
    db.close()


@pytest.mark.parametrize("range_ft", [10, 30])
def test_owned_source_spell_spends_mp_and_restores_state_and_rng(library, range_ft):
    row = next(
        r for r in library.all() if r["attributes"]["source_spell_v1"]["range_ft"] == range_ft
    )
    assert not is_descriptive(row)
    s = campaign(hp=12)
    commit(s, preview(library, s, row["id"], "source_formula"))
    take(s, "source_formula")
    s.perform_gameplay("encounter", {"enemies": ["wounded"]}, "begin-source-magic")
    point = s.gameplay["source_rules_v3"]["positions"]["wounded"]["point"]
    s.perform_gameplay(
        "source_move", {"position": [point[0] - 5, point[1], point[2]]}, "approach-source-target"
    )
    before = s.gameplay["mp"]
    s.perform_gameplay(
        "library_magic", {"item": "source_formula", "target": "wounded"}, "cast-source-magic"
    )
    assert s.gameplay["mp"] == before - 1
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
    assert Session.from_dict(s.to_dict(), version=31).dice.checkpoint() == s.dice.checkpoint()


def test_missing_target_and_unowned_formula_cannot_spend_or_roll(library):
    s = campaign(hp=12)
    row = library.all()[0]
    commit(s, preview(library, s, row["id"], "source_formula"))
    before = s.to_dict()
    with pytest.raises(ValueError):
        s.perform_gameplay(
            "library_magic", {"item": "source_formula", "target": "wounded"}, "unowned-source"
        )
    assert s.to_dict() == before
    take(s, "source_formula")
    before = s.to_dict()
    with pytest.raises(ValueError):
        s.perform_gameplay("library_magic", {"item": "source_formula"}, "no-source-target")
    assert s.to_dict() == before


def test_source_mp_costs_are_typed_and_versioned(library):
    assert [mp_cost(i) for i in range(10)] == [1, 4, 6, 8, 10, 12, 14, 16, 18, 20]
    for value in (True, -1, 10, "1"):
        with pytest.raises(ValueError):
            mp_cost(value)
    row = library.all()[0]
    rules = deepcopy(row["attributes"]["source_spell_v1"])
    rules["mp"] = 0
    with pytest.raises(ValueError):
        validate(rules)


def test_failed_mp_and_range_checks_do_not_spend_or_roll(library):
    from rpg_vkr.domain.catalog_engine import Engine
    from rpg_vkr.unified_session import context
    from rpg_vkr.world_library.source_magic_rules import perform

    s = campaign(hp=12)
    commit(s, preview(library, s, library.all()[0]["id"], "source_formula"))
    take(s, "source_formula")
    s.perform_gameplay("encounter", {"enemies": ["wounded"]}, "prepare-failed-source-cast")
    e = Engine(s.gameplay, context(s), s.dice, {})
    e.state["mp"] = 0
    checkpoint = s.dice.checkpoint()
    with pytest.raises(ValueError, match="sufficient MP"):
        perform(e, {"item": "source_formula", "target": "wounded"})
    assert e.state["mp"] == 0 and s.dice.checkpoint() == checkpoint
    e.state["mp"] = 5
    e.state["source_rules_v3"]["positions"]["wounded"]["point"] = [1000, 0, 0]
    with pytest.raises(ValueError, match="outside range"):
        perform(e, {"item": "source_formula", "target": "wounded"})
    assert e.state["mp"] == 5 and s.dice.checkpoint() == checkpoint


def test_published_source_v3_schema_stays_frozen():
    from rpg_vkr.world_library.model import digest, schemas

    assert (
        digest(schemas()["source_features_v3"])
        == "ead94a5628520609d0e03ab3ce3c402a99e3849fa1622dcad4c15f53c50e2dec"
    )
