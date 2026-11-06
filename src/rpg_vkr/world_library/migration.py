"""Read-only SQLite export and optional PostgreSQL staging; no save replacement."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from rpg_vkr.world_library.model import digest, dump


def export_sqlite(source, destination):
    """Accept actual CatalogIndex/Knowledge snapshots, not an arbitrary SQL file."""
    source = Path(source).resolve(strict=True)
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Source exceeds engine snapshot size bound")
    wal = Path(str(source) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Export a quiescent engine backup, not a live WAL database")
    destination = Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError("Destination must be a new file")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        rows = db.execute("SELECT version,payload FROM snapshot LIMIT 2").fetchall()
        if len(rows) != 1:
            raise ValueError("Expected one engine snapshot")
        version, payload = rows[0]
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError("Snapshot exceeds engine bound")
        snapshot = json.loads(payload)
        # Verify all historical rules/replay with the application's real decoder.
        from rpg_vkr.application import Session

        session = Session.from_dict(snapshot, version=version)
        from rpg_vkr.storage.catalog import live_records

        definitions, instances = live_records(session)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("Source changed during export; retry from a quiescent backup")
    envelope = {
        "format": "world-library-sqlite-stage-1",
        "source_sha256": before,
        "schema_version": version,
        "snapshot": snapshot,
        "definitions": definitions,
        "instances": instances,
        "world_id": session.campaign.world_id,
    }
    envelope["digest"] = digest(envelope)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(dump(envelope))
    return envelope


def stage(library, envelope):
    """Immutable world-scoped legacy projection, preserving original IDs and payloads.

    This is an opt-in archival projection, not a switch of the game's save backend.
    """
    copy = dict(envelope)
    checksum = copy.pop("digest")
    if checksum != digest(copy) or copy["format"] != "world-library-sqlite-stage-1":
        raise ValueError("Staging checksum/format mismatch")
    # Validate serialized source through the actual engine before any write.
    from rpg_vkr.application import Session
    from rpg_vkr.storage.catalog import live_records

    session = Session.from_dict(copy["snapshot"], version=copy["schema_version"])
    definitions, instances = live_records(session)
    if (
        definitions != copy["definitions"]
        or instances != copy["instances"]
        or session.campaign.world_id != copy["world_id"]
    ):
        raise ValueError("Projection differs from verified engine snapshot")
    world = copy["world_id"]
    with library.transaction():
        old = library.execute("SELECT source_digest FROM wl_worlds WHERE id=?", (world,)).fetchone()
        if old:
            if old[0] != checksum:
                raise ValueError("World already staged from another snapshot")
            return
        library.execute(
            "INSERT INTO wl_worlds VALUES(?,?,?,?,?)",
            (world, str(copy["schema_version"]), 0, checksum, dump(copy["snapshot"])),
        )
        for id, row in copy["definitions"].items():
            library.execute(
                "INSERT INTO wl_legacy_definitions VALUES(?,?,?)", (world, id, dump(row))
            )
        for id, row in copy["instances"].items():
            library.execute(
                "INSERT INTO wl_legacy_instances VALUES(?,?,?,?,?)",
                (world, id, row["definition_id"], row["quantity"], dump(row)),
            )
        library.execute(
            "INSERT INTO wl_audit(actor,action,subject,payload) VALUES(?,?,?,?)",
            (
                "engine/migration",
                "stage_snapshot",
                world,
                dump({"digest": checksum, "source_sha256": copy["source_sha256"]}),
            ),
        )
