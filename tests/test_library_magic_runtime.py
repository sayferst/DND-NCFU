"""Original formulas use canonical MP, ownership, finite carriers, HP and replay."""

from copy import deepcopy

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.magic_rules import compile_magic, validate
from rpg_vkr.world_library.model import ROOT, read_jsonl, validate_record
from rpg_vkr.world_library.store import Library


@pytest.fixture(scope="module")
def records():
    return read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")


@pytest.fixture
def library(tmp_path, records):
    db = Library.sqlite(tmp_path / "library.sqlite3")
    db.migrate()
    db.import_records(records)
    yield db
    db.close()


def take(session, id):
    session.perform_gameplay(
        "attempt",
        {
            "version": 1,
            "plan": {
                "operation": "take",
                "goal": "",
                "items": [id],
                "tool": "",
            },
        },
        "take-" + id,
    )


def test_all_560_original_magic_templates_have_closed_handlers(records):
    compiled = {}
    for row in records:
        if row["profile"] not in {"spell", "rune", "scroll", "combination"}:
            continue
        deps = [
            compiled[link["target"]]
            for link in row["links"]
            if link["relation"] in {"spell", "combines"}
        ]
        rules = compile_magic(row, deps)
        validate(rules)
        compiled[row["id"]] = rules
    assert len(compiled) == 560
    for id, rules in compiled.items():
        if id.startswith("wl_combination"):
            assert len(rules["effects"]) == 2


@pytest.mark.parametrize("mode,status", [(0, "shield"), (1, "light"), (3, "defence")])
def test_real_owned_formula_pays_mp_and_replays(library, mode, status):
    session = campaign(hp=12)
    commit(session, preview(library, session, f"wl_spell_0_1_{mode}", "formula"))
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.perform_gameplay("library_magic", {"item": "formula"}, "unowned")
    assert session.to_dict() == before
    take(session, "formula")
    mp = session.gameplay["mp"]
    session.perform_gameplay("library_magic", {"item": "formula"}, "cast-formula")
    assert session.gameplay["mp"] == mp - (2 + mode)
    assert any(s["op"] == status for s in session.gameplay["statuses"]["hero"])
    restored = Session.from_dict(session.to_dict(), version=31)
    assert restored.to_dict() == session.to_dict()
    assert restored.dice.checkpoint() == session.dice.checkpoint()


@pytest.mark.parametrize("profile", ["rune", "scroll"])
def test_carrier_is_consumed_once_without_free_mp_or_duplicate_cast(library, profile):
    session = campaign(hp=12)
    commit(session, preview(library, session, f"wl_{profile}_0_1_0", "carrier"))
    take(session, "carrier")
    mp = session.gameplay["mp"]
    session.perform_gameplay("library_magic", {"item": "carrier"}, "activate-carrier")
    assert session.gameplay["mp"] == mp - 2
    assert not any(e.id == "carrier" for e in session.catalog.entities)
    before = session.to_dict()
    checkpoint = session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.perform_gameplay("library_magic", {"item": "carrier"}, "duplicate")
    assert session.to_dict() == before and session.dice.checkpoint() == checkpoint
    assert Session.from_dict(before, version=31).to_dict() == before


def test_combination_cost_is_sum_and_both_effects_execute(library):
    session = campaign(hp=12)
    commit(session, preview(library, session, "wl_combination_0", "combined"))
    take(session, "combined")
    mp = session.gameplay["mp"]
    session.perform_gameplay("library_magic", {"item": "combined"}, "cast-combined")
    assert session.gameplay["mp"] == mp - 5
    assert {"shield", "light"} <= {s["op"] for s in session.gameplay["statuses"]["hero"]}
    assert Session.from_dict(session.to_dict(), version=31).to_dict() == session.to_dict()


def test_invalid_target_and_level_leave_all_resources_rng_and_history_unchanged(library):
    session = campaign(hp=12)
    commit(session, preview(library, session, "wl_spell_0_1_2", "attack_formula"))
    take(session, "attack_formula")
    before = session.to_dict()
    checkpoint = session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.perform_gameplay("library_magic", {"item": "attack_formula"}, "self-harm")
    assert session.to_dict() == before and session.dice.checkpoint() == checkpoint
    session.perform_gameplay("encounter", {"enemies": ["wounded"]}, "start")
    session.perform_gameplay(
        "library_magic", {"item": "attack_formula", "target": "wounded"}, "attack-cast"
    )
    assert Session.from_dict(session.to_dict(), version=31).to_dict() == session.to_dict()


def test_descriptive_legacy_and_arbitrary_code_are_not_magic_programs(records):
    row = deepcopy(next(r for r in records if r["profile"] == "spell"))
    row["attributes"].pop("rules")
    validate_record(row)  # Legacy descriptive revisions remain valid.
    with pytest.raises(ValueError, match="handler"):
        compile_magic(row, [])
    row = deepcopy(next(r for r in records if r["profile"] == "spell"))
    row["attributes"]["rules"]["sql"] = "DROP TABLE saves"
    with pytest.raises(ValueError):
        validate_record(row)
