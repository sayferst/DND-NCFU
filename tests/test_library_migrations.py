"""Upgrade a populated V1 library, preserving immutable revisions, links and audit."""

import json
from copy import deepcopy

import pytest

from rpg_vkr.world_library.model import ROOT, all_records, digest, dump, read_jsonl
from rpg_vkr.world_library.store import Library


def bootstrap_v1(library):
    """Create the actual published V1 schema, not the current migrate() output."""
    sql = (ROOT / "data/world_library/migrations/001_library.sql").read_text("utf-8")
    sql = sql.replace(
        "INTEGER PRIMARY KEY GENERATED_BY_BACKEND",
        "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
        if library.postgres
        else "INTEGER PRIMARY KEY AUTOINCREMENT",
    )
    if library.postgres:
        sql = sql.replace("payload TEXT", "payload JSONB").replace(
            "schema_json TEXT", "schema_json JSONB"
        )
    with library.transaction():
        library.execute(
            "CREATE TABLE wl_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
        )
        for statement in sql.split(";"):
            if statement.strip():
                library.execute(statement)
        library.execute("INSERT INTO wl_migrations VALUES(1,?)", (digest(sql),))
        library.execute(
            "INSERT INTO wl_schemas VALUES(?,?)", ("old_schema", dump({"type": "object"}))
        )
        if library.postgres:
            library.execute("CREATE INDEX wl_attributes_gin ON wl_versions USING GIN (payload)")
            library.execute(
                "CREATE INDEX wl_search_fts ON wl_templates USING GIN "
                "(to_tsvector('simple',search_text))"
            )
    return digest(sql)


def test_populated_v1_upgrade_imports_every_record_and_preserves_history(tmp_path):
    library = Library.sqlite(tmp_path / "old-library.sqlite3")
    try:
        old_checksum = bootstrap_v1(library)
        seed = read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")
        library.import_records(seed)
        changed = deepcopy(seed[0])
        changed["description"] += " Установленная прежняя ревизия."
        library.import_records([changed], expected={changed["id"]: 1})
        links = library.execute("SELECT * FROM wl_links ORDER BY id,revision,ordinal").fetchall()
        audit = library.execute("SELECT * FROM wl_audit ORDER BY sequence").fetchall()
        library.migrate()
        assert library.get(changed["id"], 1) == seed[0]
        assert library.get(changed["id"]) == changed
        assert (
            library.execute("SELECT * FROM wl_links ORDER BY id,revision,ordinal").fetchall()
            == links
        )
        assert library.execute("SELECT * FROM wl_audit ORDER BY sequence").fetchall() == audit
        assert (
            library.execute("SELECT checksum FROM wl_migrations WHERE version=1").fetchone()[0]
            == old_checksum
        )
        old_schema = library.execute(
            "SELECT schema_json FROM wl_schema_revisions WHERE id='old_schema'"
        ).fetchone()[0]
        assert json.loads(old_schema) == {"type": "object"}
        rows = {r["id"]: r for r in all_records()}
        rows[changed["id"]] = changed
        library.import_records(list(rows.values()))
        assert len(library.all()) == 27426
        assert (
            library.execute(
                "SELECT COUNT(*) FROM wl_links WHERE relation IN ('parent','child')"
            ).fetchone()[0]
            == 19542
        )
        assert library.execute("PRAGMA foreign_key_check").fetchall() == []
        library.migrate()
        assert library.execute("SELECT COUNT(*) FROM wl_migrations").fetchone()[0] == 8
        assert library.get(changed["id"]) == changed
    finally:
        library.close()


def test_changed_migration_checksum_is_rejected_without_changes(tmp_path):
    library = Library.sqlite(tmp_path / "library.sqlite3")
    try:
        library.migrate()
        with library.transaction():
            library.execute("UPDATE wl_migrations SET checksum='modified' WHERE version=2")
        before = library.execute("SELECT * FROM wl_migrations ORDER BY version").fetchall()
        with pytest.raises(ValueError, match="checksum"):
            library.migrate()
        assert library.execute("SELECT * FROM wl_migrations ORDER BY version").fetchall() == before
    finally:
        library.close()
