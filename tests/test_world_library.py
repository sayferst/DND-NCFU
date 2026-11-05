"""Global library, engine boundary, immutable exports and backend parity."""

import hashlib
import json
import os
from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.storage.catalog import CatalogIndex
from rpg_vkr.storage.knowledge import export_session, restore_session
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.migration import export_sqlite, stage
from rpg_vkr.world_library.model import ROOT, digest, read_jsonl, validate_bundle, validate_record
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


def test_seed_manifest_and_determinism(records):
    manifest = json.loads((ROOT / "data/world_library/manifest.json").read_text(encoding="utf-8"))
    assert len(records) == manifest["records"] == 2864
    assert digest(records) == manifest["sha256_canonical_records"]
    assert len({r["profile"] for r in records}) == 23
    assert manifest["human_reviewed"] == 0


def test_rpgd100_facts_coverage_and_nonexecution(library):
    facts = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    main = [r for r in facts if r["attributes"]["source_catalog"] == "bestiary_dnd5e"]
    assert len(main) == 2874
    assert len({r["id"] for r in facts}) == len(facts)
    assert all(r["provenance"]["origin"] == "source-facts/original-description" for r in facts)
    library.import_records(facts)
    with pytest.raises(ValueError, match="handler"):
        preview(library, Session(seed=1), main[0]["id"], "reference_monster")


def test_literal_parser_does_not_execute():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from import_rpgd100_facts import literal_array

    assert literal_array("const x=[{id:'a', flag:!0, n:12}];throw 1") == [
        {"id": "a", "flag": True, "n": 12}
    ]
    with pytest.raises(ValueError):
        literal_array("const x=[dangerous()]")


def test_all_catalog_entries_have_canonical_ids():
    from rpg_vkr.world_library.model import all_records

    rows = all_records()
    assert len(rows) == 27426
    ids = {r["id"] for r in rows}
    mapping = [
        json.loads(line)
        for line in (ROOT / "data/world_library/rpgd100-source-ids.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(mapping) == 24527
    assert all(r["canonical_id"] in ids for r in mapping)
    assert len({r["catalog"] for r in mapping}) == 55


def test_creature_stats_fallback_and_canonical_combat(library):
    from test_owner_rules_runtime import campaign

    from rpg_vkr.world_library.creature_rules import compile_creature

    facts = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    row = next(r for r in facts if r["attributes"]["attacks"] and 1 <= r["attributes"]["hp"] <= 5)
    library.import_records(facts)
    props = compile_creature(row)
    assert props["hp_max"] == row["attributes"]["hp"]
    assert props["attack_bonus"] == row["attributes"]["attacks"][0]["bonus"]
    assert "attack_bonus" not in props["homebrew_fields"]
    missing = deepcopy(row)
    missing["attributes"]["hp"] = 0
    fallback = compile_creature(missing)
    assert fallback["hp_max"] > 0 and "hp_max" in fallback["homebrew_fields"]
    session = campaign(hp=12)
    before = session.to_dict()
    proposal = preview(library, session, row["id"], "source_enemy")
    assert session.to_dict() == before
    commit(session, proposal)
    session.perform_gameplay(
        "encounter", {"enemies": ["source_enemy"], "allies": []}, "source-encounter"
    )
    restored = Session.from_dict(session.to_dict(), version=31)
    assert restored.to_dict() == session.to_dict()
    assert restored.dice.checkpoint() == session.dice.checkpoint()


def test_complete_equipment_index_and_visual_variants(library):
    from rpg_vkr.world_library.appearance import appearance

    rows = read_jsonl(ROOT / "data/world_library/rpgd100-equipment-facts.jsonl")
    assert len(rows) == 391
    assert len({row["id"] for row in rows}) == 391
    assert sum(row["attributes"]["missing_numeric_facts"] for row in rows) == 6
    library.import_records(rows)
    with pytest.raises(ValueError, match="handler"):
        preview(library, Session(seed=1), rows[0]["id"], "unpriced_source_item")
    assert appearance("a", "Слизь", "слизь", "большая") == appearance(
        "a", "Слизь", "слизь", "большая"
    )
    assert appearance("a", "Слизь", "слизь", "большая") != appearance(
        "b", "Слизь", "слизь", "большая"
    )
    assert "бескостная" in appearance("a", "Слизь", "слизь", "большая")


@pytest.mark.parametrize(
    "mutation", ["boolean_number", "missing", "unknown", "excess_damage", "currency", "nonfinite"]
)
def test_strict_validation(records, mutation):
    row = deepcopy(next(r for r in records if r["profile"] == "weapon"))
    if mutation == "boolean_number":
        row["attributes"]["durability"] = True
    elif mutation == "missing":
        del row["attributes"]["hands"]
    elif mutation == "unknown":
        row["attributes"]["execute_sql"] = "DROP TABLE campaigns"
    elif mutation == "excess_damage":
        row["attributes"]["damage_count"] = 30
    elif mutation == "currency":
        row["price_cp"] = -1
    else:
        row["attributes"]["durability"] = float("nan")
    with pytest.raises(ValueError):
        validate_record(row)


def test_references_duplicates_cycles(records):
    bad = deepcopy(records)
    bad[0]["links"] = [
        {"relation": "component", "target": bad[1]["id"], "quantity": 1, "role": "test"}
    ]
    bad[1]["links"] = [
        {"relation": "component", "target": bad[0]["id"], "quantity": 1, "role": "test"}
    ]
    with pytest.raises(ValueError, match="cycle"):
        validate_bundle(bad)
    bad[1]["links"][0]["target"] = "wl_missing"
    with pytest.raises(ValueError, match="reference"):
        validate_bundle(bad)
    with pytest.raises(ValueError, match="Duplicate"):
        validate_bundle(records + [records[0]])


def test_idempotency_updates_rollback_export(library, records, tmp_path):
    audits = library.execute("SELECT COUNT(*) FROM wl_audit").fetchone()[0]
    library.migrate()
    library.import_records(records)
    assert library.execute("SELECT COUNT(*) FROM wl_audit").fetchone()[0] == audits
    changed = deepcopy(records[0])
    changed["description"] += " Проверенная поправка."
    library.import_records([changed], expected={changed["id"]: 1})
    assert library.get(changed["id"], 1) == records[0]
    assert library.get(changed["id"]) == changed
    with pytest.raises(ValueError, match="Stale"):
        library.import_records([records[0]], expected={changed["id"]: 1})
    invalid = deepcopy(records[1])
    invalid["links"] = [
        {"relation": "component", "target": "wl_absent", "quantity": 1, "role": "test"}
    ]
    with pytest.raises(ValueError):
        library.import_records([records[0], invalid], expected={changed["id"]: 2, invalid["id"]: 1})
    assert library.revision(changed["id"]) == 2
    export = tmp_path / "export.jsonl"
    library.export(export)
    assert len(read_jsonl(export)) == len(records)
    with pytest.raises(FileExistsError):
        library.export(export)


def test_search_injection_retire_and_pending(library, records):
    assert library.search("лук", "physical.weapon")
    assert library.search(records[0]["id"])[0] == records[0]
    assert not library.search("' OR 1=1 --")
    assert not library.search("%")
    row = deepcopy(records[0])
    row["id"] = "wl_new_proposal"
    row["name"] = "Новая авторская партия"
    proposal = library.propose(row, model="test-model", prompt_version="v1")
    with pytest.raises(KeyError):
        library.get(row["id"])
    library.approve(proposal, actor="test-engine")
    assert library.get(row["id"]) == row
    library.retire(row["id"], 1, actor="test-engine")
    with pytest.raises(KeyError):
        library.get(row["id"])
    assert library.get(row["id"], 1) == row


def test_foreign_database_refused(tmp_path):
    import sqlite3

    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE user_save(payload TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Foreign"):
        Library.sqlite(path)
    assert path.read_bytes() == before


def test_library_window(qt_app, library):
    from rpg_vkr.world_library.ui import LibraryWindow

    window = LibraryWindow(library)
    window.query.setText("Короткий лук")
    window.search()
    assert window.results.count() > 0
    window.results.setCurrentRow(0)
    assert "invented/homebrew" in window.details.toPlainText()
    equipment = read_jsonl(ROOT / "data/world_library/rpgd100-equipment-facts.jsonl")
    window.rows = [next(row for row in equipment if row["attributes"]["facts"])]
    window.show_record(0)
    assert "source-facts/original-description" in window.details.toPlainText()
    references = read_jsonl(ROOT / "data/world_library/rpgd100-reference-index.jsonl")
    window.rows = [next(r for r in references if r["attributes"]["record_type"] == "spell")]
    window.show_record(0)
    shown = window.details.toPlainText()
    assert '"source_fields"' in shown
    assert "Цена: справочное значение не задано" in shown
    window.close()


def test_engine_instance_boundary_replay(library, tmp_path):
    session = Session(seed=42)
    before = session.to_dict()
    checkpoint = session.dice.checkpoint()
    record = preview(library, session, "wl_weapon_10_0", "library_bow_one")
    assert session.to_dict() == before
    commit(session, record)
    assert session.world == Session.from_dict(before, version=session.schema_version).world
    assert session.dice.checkpoint() == checkpoint
    assert session.catalog.entities[-1].parent_id == session.current_place_id
    assert session.catalog.entities[-1].owner_id == ""
    with pytest.raises(ValueError):
        commit(session, record)
    source = tmp_path / "instance.sqlite3"
    export_session(session, source)
    restored = restore_session(source)
    assert restored.to_dict() == session.to_dict()
    with pytest.raises(ValueError):
        preview(library, session, "wl_weapon_10_0", "library_bow_one")
    with pytest.raises(ValueError, match="handler"):
        preview(library, session, "wl_spell_0_1_0", "illegal_spell")


def test_sqlite_migration_real_projection(library, tmp_path):
    session = Session(seed=8)
    source = tmp_path / "source.sqlite3"
    index = CatalogIndex(session)
    index.export(source)
    index.close()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / "stage.json"
    envelope = export_sqlite(source, destination)
    stage(library, envelope)
    stage(library, envelope)
    assert library.execute("SELECT COUNT(*) FROM wl_worlds").fetchone()[0] == 1
    assert library.execute("SELECT COUNT(*) FROM wl_legacy_instances").fetchone()[0] == len(
        envelope["instances"]
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert restore_session(source).to_dict() == session.to_dict()
    with pytest.raises(ValueError):
        export_sqlite(source, source)
    forged = deepcopy(envelope)
    forged["instances"].clear()
    forged["digest"] = digest({k: v for k, v in forged.items() if k != "digest"})
    with pytest.raises(ValueError, match="Projection"):
        stage(library, forged)


@pytest.mark.skipif(
    not os.environ.get("DND_LIBRARY_TEST_DSN"), reason="Local PostgreSQL DSN not configured"
)
def test_postgresql_parity(records, tmp_path):
    # Requires a dedicated EMPTY database, never a user's game database.
    library = Library.postgres(os.environ["DND_LIBRARY_TEST_DSN"])
    try:
        from test_library_migrations import bootstrap_v1

        bootstrap_v1(library)
        library.import_records(records)
        assert len(library.all()) == len(records)
        assert library.search("лук", "physical.weapon")
        library.import_records(records)
        assert library.revision(records[0]["id"]) == 1
        changed = deepcopy(records[0])
        changed["description"] += " Проверка версии PostgreSQL."
        library.import_records([changed], expected={changed["id"]: 1})
        assert library.get(changed["id"], 1) == records[0]
        assert library.get(changed["id"]) == changed
        with pytest.raises(ValueError, match="Stale"):
            library.import_records([records[0]], expected={changed["id"]: 1})
        assert library.revision(changed["id"]) == 2
        library.migrate()  # Upgrade the populated published V1 schema before full import.
        from rpg_vkr.world_library.model import all_records

        full = {r["id"]: r for r in all_records()}
        full[changed["id"]] = changed
        library.import_records(list(full.values()))
        assert len(library.all()) == 27426
        session = Session(seed=3)
        source = tmp_path / "pg-source.sqlite3"
        export_session(session, source)
        stage(library, export_sqlite(source, tmp_path / "pg-stage.json"))
    finally:
        library.close()
