"""Actual tar/gzip fixtures exercise full streams, quarantine, resume and byte integrity."""

import gzip
import hashlib
import io
import json
import tarfile

import pytest

from training.fireball_raw import inspect_stream


def archive():
    stream = io.BytesIO()
    original = (
        b'{"event_type":"message","author_bot":false,'
        b'"custom_spell":"Violet Gate","hp":null}\n{broken\n'
    )
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        blob = gzip.compress(original)
        info = tarfile.TarInfo("anonymized/data/combat.jsonl.gz")
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))
    return stream.getvalue(), original


def test_entire_stream_counts_hash_and_audit_is_not_canonical(tmp_path):
    blob, _ = archive()
    report = inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)})
    assert report["archive_sha256"] == hashlib.sha256(blob).hexdigest()
    assert report["records"] == {"lines": 2, "parsed": 1, "quarantine": 1}
    assert report["canonical_storage"] == "NOT_MATERIALIZED_AUDIT_ONLY"
    resumed = inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)})
    assert resumed["records"] == report["records"] and resumed["resumed_members"] == 1


def test_canonical_keeps_unknown_values_and_quarantine_bytes(tmp_path):
    import base64

    blob, original = archive()
    report = inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)}, canonical=True)
    path = next((tmp_path / "canonical").glob("*.gz"))
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    assert rows[0]["original"]["custom_spell"] == "Violet Gate"
    assert rows[0]["original"]["hp"] is None and rows[0]["role"] == "human_role_unknown"
    assert base64.b64decode(rows[1]["raw_line_base64"]) == original.splitlines(keepends=True)[1]
    assert report["canonical_storage"] == "COMPLETE" and report["train_admitted"] == 0
    assert (
        inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)}, canonical=True)[
            "resumed_members"
        ]
        == 1
    )


def test_bad_outer_crc_or_truncation_cannot_produce_complete_report(tmp_path):
    blob, _ = archive()
    bad = bytearray(blob)
    bad[-8] ^= 1
    with pytest.raises((OSError, EOFError)):
        inspect_stream(io.BytesIO(bad), tmp_path, {"bytes": len(blob)})
    assert not (tmp_path / "report.json").exists()


def test_changed_remote_binding_is_rejected(tmp_path):
    blob, _ = archive()
    inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob), "etag": "first"})
    with pytest.raises(ValueError, match="Changed source binding"):
        inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob), "etag": "second"})


def test_index_only_keeps_metadata_without_extracting_source_body(tmp_path):
    import sqlite3
    import zlib

    blob, _ = archive()
    report = inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)}, link_index=True)
    db = sqlite3.connect(tmp_path / "members.sqlite")
    payload = db.execute("SELECT payload FROM event_indexes").fetchone()[0]
    events = [json.loads(line) for line in zlib.decompress(payload).splitlines()]
    assert events[0][:3] == ["message", "human_role_unknown", "explicit_author_bot"]
    assert events[1][0] == "QUARANTINE"
    assert not (tmp_path / "canonical").exists() and not (tmp_path / "filtered-members").exists()
    assert report["canonical_storage"] == "NOT_MATERIALIZED_AUDIT_ONLY"
    db.close()


def test_storage_limit_stops_before_source_consumption(tmp_path):
    blob, _ = archive()
    stream = io.BytesIO(blob)
    with pytest.raises(OSError, match="OUTPUT_BUDGET_REACHED"):
        inspect_stream(stream, tmp_path, {"bytes": len(blob)}, max_output_mib=0)
    assert stream.tell() == 0 and not (tmp_path / "report.json").exists()


def test_free_space_reserve_stops_before_source_consumption(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from training import fireball_raw

    monkeypatch.setattr(fireball_raw.shutil, "disk_usage", lambda _: SimpleNamespace(free=100))
    blob, _ = archive()
    with pytest.raises(OSError, match="FREE_SPACE_RESERVE_REACHED"):
        inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)})


def test_native_linker_checks_type_bounds_and_preserves_role_uncertainty():
    from training.fireball_raw_links import link_record

    events = [
        ["message", "human_role_unknown", "explicit_author_bot", "opaque"],
        ["command", "unknown", "not_available", None],
    ]
    links = link_record({"refs": {"after_idxs": [0, 1, 8, None, False]}}, events)
    assert [v["status"] for v in links] == [
        "INDEX_AND_TYPE_CONFIRMED",
        "INDEX_TYPE_REVIEW",
        "INDEX_UNAVAILABLE",
        "INDEX_UNAVAILABLE",
        "INDEX_UNAVAILABLE",
    ]
    assert links[0]["role"] == "human_role_unknown"
    assert all(v["role"] != "DM" for v in links)


def test_full_native_pair_index_and_link_ledger_without_hf_inference(tmp_path):
    from training.fireball_raw_links import resolve

    packed = io.BytesIO()
    raw = {"event_type": "message", "author_bot": False, "content": "The portal opens."}
    filtered = {"after_utterances": ["The portal opens."], "after_idxs": [0]}
    with tarfile.open(fileobj=packed, mode="w:gz") as tar:
        for folder, value in (("data", raw), ("filtered", filtered)):
            blob = gzip.compress((json.dumps(value) + "\n").encode())
            info = tarfile.TarInfo("anonymized/" + folder + "/combat.jsonl.gz")
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    blob = packed.getvalue()
    root = tmp_path / "source"
    inspect_stream(io.BytesIO(blob), root, {"bytes": len(blob)}, link_index=True)
    report = resolve(root, tmp_path / "links")
    assert report["counts"]["native_filtered_records"] == 1
    assert report["after_reference_roles"] == {"human_role_unknown": 1}
    assert report["counts"]["hf_content_candidate_records"] == 0
    assert report["link_statuses"] == {"INDEX_AND_TYPE_CONFIRMED": 1}
    assert report["train_admitted"] == 0


def test_incomplete_canonical_output_is_preserved_and_rebuilt(tmp_path):
    name = hashlib.sha256(b"anonymized/data/combat.jsonl.gz").hexdigest() + ".jsonl.gz"
    dest = tmp_path / "canonical" / name
    dest.parent.mkdir()
    partial = dest.with_name(dest.name + ".partial")
    partial.write_bytes(b"interrupted derivative")
    blob, _ = archive()
    report = inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)}, canonical=True)
    assert report["canonical_storage"] == "COMPLETE" and dest.is_file()
    assert next(dest.parent.glob("*.interrupted-*")).read_bytes() == b"interrupted derivative"


def test_committed_pending_canonical_file_recovers_after_rename_interruption(tmp_path):
    blob, _ = archive()
    inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)}, canonical=True)
    dest = next((tmp_path / "canonical").glob("*.gz"))
    dest.rename(str(dest) + ".partial")
    result = inspect_stream(io.BytesIO(blob), tmp_path, {"bytes": len(blob)}, canonical=True)
    assert result["resumed_members"] == 1 and dest.is_file()


def test_bounded_filtered_mirror_preserves_original_bytes_and_source_identity(tmp_path):
    import sqlite3

    from training.fireball_raw_filtered import mirror

    buf = io.BytesIO()
    original = {"custom_spell": "Violet Gate", "hp": None}
    payload = gzip.compress((json.dumps(original) + "\n").encode())
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        entry = tarfile.TarInfo("anonymized/filtered/combat.jsonl.gz")
        entry.size = len(payload)
        tar.addfile(entry, io.BytesIO(payload))
    blob = buf.getvalue()
    root = tmp_path / "audit"
    inspect_stream(io.BytesIO(blob), root, {"bytes": len(blob)})
    out = tmp_path / "mirror"
    report = mirror(io.BytesIO(blob), root, out)
    db = sqlite3.connect(out / "filtered.sqlite")
    assert db.execute("SELECT payload FROM filtered").fetchone()[0] == payload
    assert report["status"] == "COMPLETE" and report["raw_body_storage"] == "NOT_COPIED"
    db.execute("UPDATE filtered SET payload=?", (b"tampered",))
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="Immutable filtered source changed"):
        mirror(io.BytesIO(blob), root, out)
