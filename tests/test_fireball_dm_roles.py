"""DM labels require explicit prior state evidence, stable bytes and exact references."""

import gzip
import hashlib
import io
import json
import sqlite3
import tarfile
import zlib

import pytest

from training.fireball_dm_roles import extract_member, scan
from training.fireball_raw import inspect_stream


def events():
    return [
        {"event_type": "message", "author_id": "a", "author_bot": False, "content": "Before state"},
        {"event_type": "combat_state_update", "data": {"dm": "a"}},
        {"event_type": "message", "author_id": "a", "content": "The door opens."},
        {
            "event_type": "message",
            "author_id": "b",
            "author_bot": False,
            "content": "I step inside.",
        },
        {"event_type": "combat_state_update", "data": {"dm": "b"}},
        {"event_type": "message", "author_id": "a", "content": "I move back."},
        {"event_type": "message", "author_id": "b", "content": "A light flickers."},
        {"event_type": "message", "author_id": "b", "author_bot": True, "content": "Bot output"},
    ]


def lines(values):
    return [(json.dumps(e) + "\n").encode() for e in values]


def source():
    stream = io.BytesIO()
    parts = {
        "anonymized/data/a.jsonl.gz": b"".join(lines(events())),
        "anonymized/filtered/a.jsonl.gz": b"".join(
            lines(
                [
                    {
                        "before_idxs": [0, 3],
                        "after_idxs": [2, 5, 6, 7],
                        "before_state_idx": 1,
                        "after_state_idx": 4,
                    },
                ]
            )
        ),
    }
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, value in parts.items():
            compressed = gzip.compress(value)
            info = tarfile.TarInfo(name)
            info.size = len(compressed)
            archive.addfile(info, io.BytesIO(compressed))
    return stream.getvalue()


def test_dm_changes_are_local_and_future_authority_never_labels_old_message():
    messages, changes, counts = extract_member(iter(lines(events())), {0, 2, 3, 5, 6, 7, 99})
    assert [x["role"] for x in messages] == [
        "unknown",
        "dungeon_master_account",
        "non_dm_account",
        "non_dm_account",
        "dungeon_master_account",
        "bot",
    ]
    assert [x["state_index"] for x in changes] == [1, 4]
    assert messages[1]["role_evidence"]["state_index"] < messages[1]["index"]
    assert counts["missing_indices"] == 1
    assert messages[1]["content"] == "The door opens."


def test_missing_dm_or_corrupt_state_cannot_reuse_old_authority():
    values = lines(events()[:3]) + [b"{bad\n"] + lines(events()[2:3])
    messages, _, counts = extract_member(iter(values), {2, 4})
    assert messages[0]["role"] == "dungeon_master_account"
    assert messages[1]["role"] == "unknown" and counts["quarantine"] == 1
    values = events()[:3] + [{"event_type": "combat_state_update", "data": {}}] + events()[2:3]
    messages, _, _ = extract_member(iter(lines(values)), {4})
    assert messages[0]["role"] == "unknown"


def test_real_stream_is_hash_bound_resumable_and_retains_only_referenced_messages(tmp_path):
    blob = source()
    index, output = tmp_path / "old", tmp_path / "new"
    inspect_stream(io.BytesIO(blob), index, {"bytes": len(blob)}, link_index=True)
    before = (index / "members.sqlite").read_bytes()
    result = scan(io.BytesIO(blob), index, output)
    assert result["archive_sha256"] == hashlib.sha256(blob).hexdigest()
    assert result["native_filtered_groups"] == 1
    assert result["counts"]["retrieved_indices"] == 6
    assert result["human_approved"] == result["train_admitted"] == 0
    with sqlite3.connect(output / "roles.sqlite") as db:
        payload = db.execute("SELECT messages FROM members").fetchone()[0]
        captured = json.loads(zlib.decompress(payload))
    assert {m["index"] for m in captured} == {0, 2, 3, 5, 6, 7}
    assert scan(io.BytesIO(blob), index, output)["resumed_role_groups"] == 1
    assert (index / "members.sqlite").read_bytes() == before


def test_changed_archive_and_modified_role_cache_do_not_pass(tmp_path):
    blob = source()
    index, output = tmp_path / "old", tmp_path / "new"
    inspect_stream(io.BytesIO(blob), index, {"bytes": len(blob)}, link_index=True)
    scan(io.BytesIO(blob), index, output)
    with sqlite3.connect(output / "roles.sqlite") as db:
        db.execute("UPDATE members SET messages=?", (b"tampered",))
    with pytest.raises(ValueError, match="Cached role index changed"):
        scan(io.BytesIO(blob), index, output)
    assert list(output.glob("failure-*.json"))


def test_budget_guard_consumes_no_archive_bytes(tmp_path):
    blob = source()
    index = tmp_path / "old"
    inspect_stream(io.BytesIO(blob), index, {"bytes": len(blob)}, link_index=True)
    stream = io.BytesIO(blob)
    with pytest.raises(OSError, match="OUTPUT_BUDGET"):
        scan(stream, index, tmp_path / "new", max_output_mib=0)
    assert stream.tell() == 0
