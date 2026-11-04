"""Preservation, temporal leakage, unfamiliar mechanics, and candidate-only task exports."""

import base64
import hashlib
import json
from copy import deepcopy

import pytest
from test_training_tokenization import CharacterTokenizer

from training.fireball_archive import connect
from training.fireball_audit import observation, refine
from training.fireball_observations import (
    TASKS,
    build_views,
    database,
    ingest,
    report,
    strict_source_json,
    task_candidates,
    unpacked,
)
from training.fireball_tasks import encode_view


def turn(name):
    return {
        "speaker_id": "123456789012345678",
        "before_utterances": ["I invoke the homebrew spell."],
        "combat_state_before": [
            {
                "name": name,
                "hp": "<44/34 HP; unknown homebrew>",
                "spells": "Unimplemented Violet Gate",
                "description": None,
                "controller_id": "99999999999999999",
            }
        ],
        "commands_norm": ['!cast "Unimplemented Violet Gate"'],
        "automation_results": ["Portal X opens; effect definition is unknown."],
        "combat_state_after": [{"name": name, "hp": None, "custom_resource": {"unknown": None}}],
        "after_utterances": ["A violet passage appears."],
        "custom_unrecognized": {"items": [None, 0, False]},
        "before_idxs": [10],
        "before_state_idx": 9,
        "command_idxs": [12],
        "after_state_idx": 14,
        "after_idxs": [15],
    }


def source(tmp_path):
    root = tmp_path
    (root / "originals/filtered").mkdir(parents=True)
    (root / "inventory.json").write_text(
        json.dumps(
            {"revision": "fixture", "entries": [{"path": f"filtered/{i}.jsonl"} for i in range(3)]}
        )
    )
    (root / "FIREBALL-tree.json").write_text('{"revision":"demo-fixture"}')
    (root / "raw-probe.json").write_text('{"status":"TEST_ONLY_NOT_PROBED"}')
    d = connect(root)
    for i in range(3):
        rows = [turn(str(i))]
        if i == 0:
            overlap = deepcopy(rows[0])
            overlap.update(before_idxs=[11], before_state_idx=11)
            overlap["before_utterances"] = ["SECOND_INPUT"]
            overlap["commands_norm"] = ["!custom second"]
            rows.append(overlap)
        raw = "".join(json.dumps(r) + "\n" for r in rows).encode()
        if i == 0:
            raw += b"{malformed\n" + b'{"duplicate":1,"duplicate":2}\n'
        (root / f"originals/filtered/{i}.jsonl").write_bytes(raw)
        d.execute(
            "INSERT INTO files VALUES(?,?,?,?,?)",
            (f"filtered/{i}.jsonl", len(raw), hashlib.sha256(raw).hexdigest(), "OK", None),
        )
    d.commit()
    d.close()
    return root


def test_all_records_and_unfamiliar_magic_preserved_with_independent_task_status(tmp_path):
    root = source(tmp_path)
    ingest(root)
    refine(root)
    splits = build_views(root)
    summary = report(root, splits)
    assert summary["observations"] == 6 and summary["lines_by_status"] == {
        "PRESERVED": 4,
        "QUARANTINE": 2,
    }
    assert summary["dispositions"] == 6 * len(TASKS) and summary["unaccounted_records"] == 0
    assert summary["split_violations"] == 0 and set(summary["views_by_split"]) == {
        "train",
        "val",
        "test",
    }
    db = database(root)
    identity = db.execute(
        "SELECT id FROM observations WHERE file='filtered/0.jsonl' AND line=1"
    ).fetchone()[0]
    original = observation(root, identity)
    assert original["original"] == turn("0") and original["source"]["revision"] == "fixture"
    for task in (
        "utterance_to_command",
        "command_to_result",
        "observed_transition",
        "grounded_utterance",
        "entity_observation",
    ):
        assert db.execute(
            "SELECT 1 FROM views WHERE observation_id=? AND task=?", (identity, task)
        ).fetchone()
    assert summary["train_admitted"] == summary["human_approved"] == 0
    quarantined = db.execute(
        "SELECT payload FROM observations WHERE status='QUARANTINE'"
    ).fetchall()
    assert all(base64.b64decode(unpacked(v[0])["raw_line_base64"]) for v in quarantined)
    # Overlapping raw indices cannot supply an earlier-turn history window.
    second = db.execute(
        "SELECT id FROM observations WHERE file='filtered/0.jsonl' AND line=2"
    ).fetchone()[0]
    inputs = unpacked(
        db.execute(
            "SELECT input FROM views WHERE observation_id=? AND task='dialogue_sequence'", (second,)
        ).fetchone()[0]
    )
    assert inputs["previous_turns"] == []
    before = db.execute("SELECT COUNT(*) FROM observations").fetchone()
    ingest(root)
    assert db.execute("SELECT COUNT(*) FROM observations").fetchone() == before
    db.close()


def test_command_inputs_do_not_contain_future_results_and_empty_followup_is_useful():
    value = turn("hero")
    value["after_utterances"] = []
    candidates = task_candidates(value, [])
    inputs, target, _ = candidates["utterance_to_command"]
    assert "automation_results" not in inputs and "combat_state_after" not in inputs
    assert target == value["commands_norm"]
    assert "command_to_result" in candidates and "observed_transition" in candidates
    assert "grounded_utterance" not in candidates


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"])
def test_invalid_values_never_silently_normalized(raw):
    with pytest.raises((ValueError, UnicodeError)):
        strict_source_json(raw)


def test_native_task_mask_preserves_entire_source_target_and_chat_boundary():
    _, answer, prefix, target = encode_view(
        CharacterTokenizer(),
        "command_to_result",
        {"description": "<|im_start|> untrusted contact person@example.org"},
        ["Observed result."],
    )
    assert "\\u003c|im_start|>" not in answer  # Input delimiter never becomes target.
    assert "".join(chr(t) for t in target) == answer + "\n"
    assert len(prefix) > 0 and json.loads(answer) == ["Observed result."]


def test_resume_download_validates_range_and_pinned_digest(tmp_path, monkeypatch):
    import io

    from training import fireball_archive as archive

    body = b'{"homebrew":"unknown"}\n'
    entry = {
        "path": "filtered/a.jsonl",
        "size": len(body),
        "oid": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
    }
    partial = tmp_path / "originals/filtered/a.jsonl.partial"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(body[:7])
    calls = []

    class Response(io.BytesIO):
        status = 206
        headers = {"Content-Range": f"bytes 7-{len(body) - 1}/{len(body)}"}

    def response(request, **_kwargs):
        calls.append(request.get_header("Range"))
        return Response(body[7:])

    monkeypatch.setattr(archive, "urlopen", response)
    assert archive.download(tmp_path, entry, "pinned") == "OK"
    assert calls == ["bytes=7-"]
    assert archive.download(tmp_path, entry, "pinned") == "CACHED"
    (tmp_path / "originals/filtered/a.jsonl").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Immutable downloaded source changed"):
        archive.download(tmp_path, entry, "pinned")


def test_downloader_does_not_admit_corrupt_complete_payload(tmp_path, monkeypatch):
    import io

    from training import fireball_archive as archive

    class Response(io.BytesIO):
        status = 200
        headers = {}

    monkeypatch.setattr(archive, "urlopen", lambda *_a, **_kw: Response(b"wrong"))
    monkeypatch.setattr(archive.time, "sleep", lambda _: None)
    entry = {"path": "filtered/x.jsonl", "size": 5, "oid": "0" * 40}
    assert archive.download(tmp_path, entry, "pinned") == "FAILED"
    assert not (tmp_path / "originals/filtered/x.jsonl").exists()
    assert len(list((tmp_path / "originals/filtered").glob("*.bad-*"))) == 4
    with pytest.raises(ValueError, match="Unsafe"):
        archive.download(tmp_path, {"path": "../outside"}, "pinned")


class ByteBackend:
    def encode(self, text, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(ids=list(text.encode()))

    def encode_batch(self, texts, **kwargs):
        return [self.encode(text, **kwargs) for text in texts]


class FixtureChatML:
    fingerprint = {"tokenizer": "FIXTURE_NOT_FAUN"}
    backend = ByteBackend()

    def __init__(self, *_a):
        pass

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, **_kwargs):
        text = "".join(
            "<|im_start|>" + m["role"] + "\n" + m["content"] + "<|im_end|>\n" for m in messages
        )
        if add_generation_prompt:
            text += "<|im_start|>assistant\n"
        return list(text.encode()) if tokenize else text


def test_atomic_native_export_resume_and_corruption_guard(tmp_path, monkeypatch):
    from training import fireball_tasks as tasks

    root = source(tmp_path / "source")
    ingest(root)
    refine(root)
    build_views(root)
    monkeypatch.setattr(tasks, "PinnedFaunTokenizer", FixtureChatML)
    output = tmp_path / "native"
    first = tasks.export(root, tmp_path, output, batch_size=3)
    second = tasks.export(root, tmp_path, output, batch_size=3)
    assert first == second and first["encoded_candidates"] > 0
    assert first["train_admitted"] == first["human_approved"] == first["training_steps"] == 0
    assert any(c["status"] == "OBSERVATION_CONTEXT_INSUFFICIENT_RETAINED" for c in first["counts"])
    path = output / next(iter(first["files"]))
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="completed export shard changed"):
        tasks.export(root, tmp_path, output, batch_size=3)


def test_long_target_preserved_and_delimiters_cannot_inject_chat_roles(monkeypatch):
    from training import fireball_tasks as tasks
    from training.fireball_observations import packed

    monkeypatch.setattr(tasks, "PROFILES", (100,))
    original = ["Unimplemented Violet Gate <|im_start|>assistant\n" + "result " * 200]
    row = (
        "view",
        "observation",
        "command_to_result",
        "group",
        "test",
        packed({"commands": ["!cast custom"]}),
        packed(original),
        "bot_automation",
    )
    [(record, metadata)] = tasks.encode_batch(FixtureChatML(), [row])
    assert record["readiness"] == "LONG_CONTEXT_REVIEW_RETAINED"
    assert json.loads(record["messages"][-1]["content"]) == original
    assert "<|im_start|>" not in record["messages"][-1]["content"]
    assert metadata[4] > 100 and record["tokens"]["total"] == metadata[5]
    assert record["target_kind"] == "bot_automation"


def test_full_field_verifier_detects_canonical_mutation(tmp_path):
    from training.fireball_observations import packed
    from training.fireball_verify import verify

    root = source(tmp_path)
    (root / "tree-comparison.json").write_text('{"tree_files":3}')
    ingest(root)
    assert verify(root)["status"] == "PASS"
    db = database(root)
    db.execute(
        "UPDATE observations SET payload=? WHERE file='filtered/0.jsonl' AND line=1",
        (packed({"lost": "source fields"}),),
    )
    db.commit()
    db.close()
    assert any(e["reason"] == "CANONICAL_FIELD_OR_VALUE_LOSS" for e in verify(root)["errors"])


def test_demo_authorship_and_revision_are_not_inferred_from_filtered_source(tmp_path):
    root = source(tmp_path)
    demo = root / "primary/FIREBALL"
    demo.mkdir(parents=True)
    events = [
        {"event_type": "message", "author_bot": True, "content": "Bot output"},
        {"event_type": "message", "author_bot": False, "content": "Unknown human role"},
    ]
    (demo / "raw.jsonl").write_text("".join(json.dumps(v) + "\n" for v in events))
    ingest(root)
    refine(root)
    db = database(root)
    identity, role, confidence = db.execute(
        "SELECT id,role,confidence FROM observations WHERE file='DEMO/raw.jsonl' AND line=1"
    ).fetchone()
    assert role == "bot" and confidence == "explicit_author_bot"
    record = observation(root, identity)
    assert record["source"]["revision"] == "demo-fixture"
    assert record["original"] == events[0]
    assert db.execute(
        "SELECT role FROM observations WHERE file='DEMO/raw.jsonl' AND line=2"
    ).fetchone() == ("human_role_unknown",)
    db.close()


def test_paged_source_reads_do_not_pin_wal_across_writes(tmp_path):
    from training.fireball_observations import paged_observations

    root = source(tmp_path)
    ingest(root)
    db = database(root)
    for _file, _line, identity in paged_observations(db, "o.id", batch_size=2):
        db.execute("UPDATE observations SET reason=? WHERE id=?", ("derived diagnostic", identity))
        db.commit()
        # A SELECT still active across yielded writes would make this checkpoint busy/locked.
        assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    db.close()


def test_duplicate_source_groups_merge_before_independent_splits(tmp_path):
    from training.fireball_observations import assign_splits, digest

    db = database(tmp_path)
    db.executemany(
        "INSERT INTO observations(id,group_id,near) VALUES(?,?,?)",
        [(str(i), "group-" + str(i), digest(["same" if i < 2 else i])) for i in range(4)],
    )
    db.commit()
    result = assign_splits(db)
    assert result["components"] == 3 and result["normalized_duplicate_clusters"] == 1
    assert (
        len(
            {
                row[0]
                for row in db.execute(
                    "SELECT split FROM split_map WHERE group_id IN ('group-0','group-1')"
                )
            }
        )
        == 1
    )
    assert {row[0] for row in db.execute("SELECT split FROM split_map")} == {"train", "val", "test"}
    db.close()


def test_complete_task_exports_reconstruct_from_db_without_new_tokenization(tmp_path, monkeypatch):
    import gzip

    from training import fireball_tasks as tasks
    from training.fireball_materialize import materialize

    root = source(tmp_path / "source")
    ingest(root)
    refine(root)
    build_views(root)
    with pytest.raises(ValueError, match="Token ledger incomplete"):
        materialize(root, tmp_path / "too-early")
    monkeypatch.setattr(tasks, "PinnedFaunTokenizer", FixtureChatML)
    export = tasks.export(root, tmp_path, tmp_path / "native")
    result = materialize(root, tmp_path / "recreated")
    originals = {}
    for name in export["files"]:
        with gzip.open(tmp_path / "native" / name, "rt") as stream:
            for line in stream:
                value = json.loads(line)
                originals[value["id"]] = value
    for name in result["files"]:
        with gzip.open(tmp_path / "recreated" / name, "rt") as stream:
            for line in stream:
                value = json.loads(line)
                if value["id"] in originals:
                    assert value == originals[value["id"]]
    assert result["views"]["entity_observation"] == 4
    assert result["new_tokenization"] is False and result["train_admitted"] == 0


def test_canonical_verifier_distinguishes_boolean_from_numeric_zero(tmp_path):
    from training.fireball_observations import packed
    from training.fireball_verify import verify

    root = source(tmp_path)
    (root / "tree-comparison.json").write_text('{"tree_files":3}')
    ingest(root)
    altered = turn("0")
    altered["custom_unrecognized"]["items"][2] = 0
    assert altered == turn("0")  # Python equality alone would miss False -> 0.
    db = database(root)
    db.execute(
        "UPDATE observations SET payload=? WHERE file='filtered/0.jsonl' AND line=1",
        (packed(altered),),
    )
    db.commit()
    db.close()
    assert verify(root)["status"] == "FAILED"


def test_task_verifier_detects_future_command_input(tmp_path):
    from training.fireball_observations import packed
    from training.fireball_verify import verify_tasks

    root = source(tmp_path)
    ingest(root)
    refine(root)
    build_views(root)
    assert verify_tasks(root)["status"] == "PASS"
    db = database(root)
    db.execute(
        "UPDATE views SET input=? WHERE task='utterance_to_command'",
        (packed({"automation_results": ["FUTURE_OUTCOME"]}),),
    )
    db.commit()
    db.close()
    assert verify_tasks(root)["failures"]["command_future_input_fields"] > 0


def test_non_finite_source_number_is_quarantined_instead_of_infinity():
    with pytest.raises(ValueError, match="non_finite_number"):
        strict_source_json(b'{"resource":1e9999}')


def test_both_demo_files_form_one_explicit_upstream_combat_group(tmp_path):
    root = source(tmp_path)
    demo = root / "primary/FIREBALL"
    demo.mkdir(parents=True)
    (demo / "raw.jsonl").write_text(
        json.dumps({"event_type": "combat_start", "combat_id": "demo-combat"}) + "\n"
    )
    (demo / "filtered_triples.jsonl").write_text(json.dumps(turn("demo-hero")) + "\n")
    ingest(root)
    refine(root)
    splits = build_views(root)
    assert splits["explicit_demo_combat_links"] == 1
    db = database(root)
    mapped = db.execute(
        "SELECT DISTINCT s.component,s.split FROM observations o JOIN split_map s "
        "ON s.group_id=o.group_id WHERE o.file LIKE 'DEMO/%'"
    ).fetchall()
    assert len(mapped) == 1
    db.close()


def test_cached_download_is_bound_to_current_pinned_git_blob(tmp_path, monkeypatch):
    from training import fireball_archive as archive

    body = b"same-size-source"
    path = tmp_path / "originals/filtered/a.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    db = archive.connect(tmp_path)
    db.execute(
        "INSERT INTO files VALUES(?,?,?,?,?)",
        ("filtered/a.jsonl", len(body), hashlib.sha256(body).hexdigest(), "OK", None),
    )
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="Immutable downloaded source changed"):
        archive.download(
            tmp_path,
            {"path": "filtered/a.jsonl", "size": len(body), "oid": "0" * 40},
            "different-pin",
        )


def test_available_demo_event_roles_resolve_without_inventing_dungeon_master(tmp_path):
    from training.fireball_audit import resolve_demo_references

    root = source(tmp_path)
    demo = root / "primary/FIREBALL"
    demo.mkdir(parents=True)
    raw = [{"event_type": "combat_state_update"} for _ in range(16)]
    raw[10] = {
        "event_type": "message",
        "author_bot": False,
        "content": "I invoke the homebrew spell.",
    }
    raw[12] = {"event_type": "command"}
    raw[15] = {"event_type": "message", "author_bot": False, "content": "A violet passage appears."}
    (demo / "raw.jsonl").write_text("".join(json.dumps(v) + "\n" for v in raw), encoding="utf-8")
    (demo / "filtered_triples.jsonl").write_text(
        json.dumps(turn("demo-hero")) + "\n", encoding="utf-8"
    )
    ingest(root)
    refine(root)
    result = resolve_demo_references(root)
    assert result["linked_after_utterance_event_roles"] == {"human_role_unknown": 1}
    assert result["dm_role"] == "NOT_AVAILABLE_NOT_INFERRED_FROM_HUMAN_FLAG"
    db = database(root)
    identity = db.execute(
        "SELECT id FROM observations WHERE file='DEMO/filtered_triples.jsonl'"
    ).fetchone()[0]
    db.close()
    link = next(
        v for v in observation(root, identity)["resolved_event_links"] if v["field"] == "after_idxs"
    )
    assert link["native_index"] == 15 and link["role_evidence"] == "explicit_author_bot"
    assert link["status"] == "INDEX_AND_TYPE_CONFIRMED"


def test_unknown_hf_shard_is_never_treated_as_one_combat():
    from training.fireball_observations import trusted_history_scope

    assert trusted_history_scope("filtered/shard.jsonl", "row", turn("hero")) is None
    assert trusted_history_scope(
        "filtered/shard.jsonl", "row", turn("hero"), {"row": "native-combat"}
    ) == ("native", "native-combat")
    assert trusted_history_scope("filtered/shard.jsonl", "row", {"combat_id": "explicit"}) == (
        "combat_id",
        '"explicit"',
    )


def test_history_overlay_materializes_corrected_context_with_new_token_metadata(
    tmp_path, monkeypatch
):
    import gzip

    from training import fireball_history_overlay as correction
    from training import fireball_tasks as tasks
    from training.fireball_materialize import materialize
    from training.fireball_observations import packed

    root = source(tmp_path / "source")
    ingest(root)
    refine(root)
    build_views(root)
    db = database(root)
    identity = db.execute("SELECT id FROM views WHERE task='dialogue_sequence' LIMIT 1").fetchone()[
        0
    ]
    db.execute(
        "UPDATE views SET input=? WHERE id=?",
        (packed({"previous_turns": [{"before_utterances": ["FOREIGN_COMBAT"]}]}), identity),
    )
    db.commit()
    db.close()
    monkeypatch.setattr(tasks, "PinnedFaunTokenizer", FixtureChatML)
    monkeypatch.setattr(correction, "PinnedFaunTokenizer", FixtureChatML)
    tasks.export(root, tmp_path, tmp_path / "original-export")
    mapping = tmp_path / "groups.jsonl.gz"
    with gzip.open(mapping, "wt", encoding="utf-8") as f:
        f.write("")
    report = correction.build(root, mapping, tmp_path, tmp_path / "overlay")
    assert report["patches"] == 1 and report["targets_modified"] is False
    result = materialize(root, tmp_path / "safe-export", tmp_path / "overlay")
    assert result["applied_history_corrections"] == 1 and result["train_admitted"] == 0
    matched = []
    for file in (tmp_path / "safe-export").glob("*.gz"):
        with gzip.open(file, "rt", encoding="utf-8") as f:
            matched.extend(json.loads(line) for line in f if identity in line)
    assert len(matched) == 1
    assert "FOREIGN_COMBAT" not in matched[0]["messages"][1]["content"]
    assert matched[0]["readiness"] == "OBSERVATION_CONTEXT_INSUFFICIENT_RETAINED"


def test_legacy_materializer_requires_history_correction_before_creating_output(tmp_path):
    from training.fireball_materialize import materialize

    root = tmp_path / "legacy"
    root.mkdir()
    (root / "coverage.json").write_text(
        '{"schema":"fireball-complete-observations-v1"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="HISTORY_CORRECTION_REQUIRED"):
        materialize(root, tmp_path / "export")
    assert not (tmp_path / "export").exists()
