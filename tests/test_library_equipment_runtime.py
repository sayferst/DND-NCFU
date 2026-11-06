"""Actual take/equip/replay and source/homebrew monetary provenance."""

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.equipment_rules import compile_equipment, validate_equipment
from rpg_vkr.world_library.model import ROOT, equipment_records, read_jsonl
from rpg_vkr.world_library.store import Library


def test_all_source_equipment_compiles_and_rejects_arbitrary_effects():
    rows = equipment_records()
    for record in rows:
        rules = compile_equipment(record)
        assert rules["price_cp"] >= 0
        validate_equipment(rules)
        with pytest.raises(ValueError):
            validate_equipment(rules | {"effect": "heal", "power": 1000000})
    staff = next(r for r in rows if r["attributes"]["source_name"] == "Боевой посох")
    assert compile_equipment(staff)["price_cp"] == 20
    assert compile_equipment(staff)["mass_g"] == 1814
    assert compile_equipment(staff)["dice"] == "1d6"


def test_imported_weapon_take_equip_and_replay(tmp_path):
    rows = equipment_records()
    row = next(r for r in rows if r["attributes"]["source_name"] == "Боевой посох")
    db = Library.sqlite(tmp_path / "library.sqlite3")
    try:
        db.migrate()
        db.import_records(read_jsonl(ROOT / "data/world_library/seed-v1.jsonl"))
        db.import_records(rows)
        session = campaign(hp=12)
        commit(session, preview(db, session, row["id"], "source_staff"))
        session.perform_gameplay(
            "attempt",
            {
                "version": 1,
                "plan": {"operation": "take", "goal": "", "items": ["source_staff"], "tool": ""},
            },
            "take-source-staff",
        )
        session.perform_gameplay("equip", {"item": "source_staff"}, "equip-source-staff")
        assert session.gameplay["weapon"] == "source_staff"
        restored = Session.from_dict(session.to_dict(), version=31)
        assert restored.to_dict() == session.to_dict()
        assert restored.dice.checkpoint() == session.dice.checkpoint()
    finally:
        db.close()
