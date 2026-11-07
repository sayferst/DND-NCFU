"""Curate source-linked master utterances, keeping complete per-source dispositions."""

import argparse
import gzip
import hashlib
import json
import math
import re
import shutil
import sqlite3
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from rpg_vkr.learning.quality import PRIVATE, UNSAFE
from training.crd3_source import REVISION as CRD3_REVISION
from training.crd3_source import read_sources
from training.fireball_observations import dumps, packed, unpacked
from training.gm_mechanics import fireball_evidence, prose_evidence, reference_evidence
from training.source_gm_curation import (
    VERSION,
    clean_source_text,
    compact_actors,
    crd3_context,
    fireball_context,
    linked_dm_targets,
    source_spans,
    text_screen,
)


def identity(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def dm_components(roles):
    parent, owner = {}, {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for member, payload in roles.execute("SELECT path,changes FROM members ORDER BY path"):
        find(member)
        for event in unpacked(payload):
            dm = event["dm_id"]
            if dm is not None:
                other = owner.setdefault(dm, member)
                parent[find(member)] = find(other)
    members = defaultdict(list)
    for key in parent:
        members[find(key)].append(key)
    components = {
        key: "fireball-dm:" + identity(sorted(values))[:24] for key, values in members.items()
    }
    order = sorted(components.values(), key=lambda value: identity([37, value]))
    train_end, val_end = math.floor(len(order) * 0.8), math.floor(len(order) * 0.9)
    splits = {
        value: "train" if i < train_end else "val" if i < val_end else "test"
        for i, value in enumerate(order)
    }
    return {key: (components[find(key)], splits[components[find(key)]]) for key in parent}


def native_members(path):
    groups = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            groups[row["native_group"].replace("/filtered/", "/data/")].append(
                row["hf_observation_id"]
            )
    return groups


def prior_scene(messages, index, states):
    history = [
        {
            "speaker_role": "game_master"
            if m["role"] == "dungeon_master_account"
            else "participant",
            "text": clean_source_text(m["content"]),
        }
        for m in messages
        if m.get("status") == "SOURCE_MESSAGE"
        and m["index"] < index
        and isinstance(m.get("content"), str)
    ][-8:]
    eligible = [(i, value) for i, value in states.items() if i < index and value is not None]
    latest = max(eligible, key=lambda row: row[0]) if eligible else None
    return {
        "task": "continue_dm_scene",
        "source_language": "en",
        "history": history,
        "observed_prior_state": latest[1] if latest else None,
        "state_index": latest[0] if latest else None,
        "history_scope": "REFERENCED_SOURCE_MESSAGES_ONLY_NOT_A_COMPLETE_RAW_CHAT",
        "mechanics_status": "NO_NEW_RESULT_RECEIPT_PROPOSE_NARRATION_NOT_VALIDATED_MUTATION",
    }


def materialize_context(value, metadata, episodes):
    """Deferred storage is lossless: verify the regenerated complete model input hash."""
    if value.get("materialization") != "CRD3_CONTEXT_FROM_PINNED_EPISODE":
        return value
    source = episodes.load(metadata["file"])
    index = metadata["turn_index"]
    text = " ".join(source["TURNS"][index]["UTTERANCES"])
    if identity(text) != metadata["source_text_sha256"]:
        raise ValueError("Referenced CRD3 utterance changed")
    normalized = clean_source_text(text)
    left, _ = metadata["normalized_span"]
    context = crd3_context(source["TURNS"], index)
    if left:
        context["earlier_same_source_utterance"] = normalized[:left]
    if identity(context) != metadata["context_sha256"]:
        raise ValueError("Reconstructed source context differs")
    return context


def curate(
    fireball_root, roles_root, native_map, crd3_root, baseline_root, output, *, resume=False
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=resume)
    if (output / "report.json").exists():
        raise FileExistsError("Completed source pools are preserved; choose a new output")
    role_report = json.loads((Path(roles_root) / "report.json").read_text(encoding="utf-8"))
    if role_report.get("status") != "COMPLETE_REFERENCED_MESSAGE_ROLE_INDEX":
        raise ValueError("Complete source DM role extraction is required")
    binding = {
        "schema": "gm-source-pool-job-v1",
        "curation_version": VERSION,
        "roles_report_sha256": file_digest(Path(roles_root) / "report.json"),
        "native_map_sha256": file_digest(Path(native_map)),
        "crd3_manifest_sha256": file_digest(Path(crd3_root) / "manifest.json"),
        "reference_manifest_sha256": file_digest(Path(baseline_root) / "manifest.json"),
        "fireball_ingested": None,
    }
    original = sqlite3.connect(
        (Path(fireball_root) / "observations.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    binding["fireball_ingested"] = identity(
        original.execute("SELECT file,sha,lines FROM ingested ORDER BY file").fetchall()
    )
    bind_job(output, binding, resume=resume)
    roles = sqlite3.connect(
        (Path(roles_root) / "roles.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    db = sqlite3.connect(output / "pool.sqlite")
    db.execute(
        "CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,source TEXT,group_id TEXT,split TEXT,"
        "unit TEXT,rank INTEGER,context BLOB,target BLOB,metadata BLOB,tags TEXT,selected INTEGER)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS source_split ON cases(source,split)")
    components = dm_components(roles)
    groups = native_members(native_map)
    if set(groups) != set(components):
        raise ValueError("Native map does not cover the same complete filtered group set")
    (output / "groups.json").write_text(json.dumps(components, indent=2) + "\n", encoding="utf-8")
    counts, rejects = Counter(), Counter()
    file_hashes = dict(original.execute("SELECT file,sha FROM ingested"))

    def guard():
        size = sum(p.stat().st_size for p in output.glob("pool.sqlite*") if p.is_file())
        if size > 224 * 1024**2 or shutil.disk_usage(output).free < 192 * 1024**2:
            raise OSError("SOURCE_POOL_STORAGE_RESERVE_REACHED")

    def store(
        source, group, split, unit, rank, context, text, metadata, tags, source_language="en"
    ):
        normalized = clean_source_text(text)
        ids = []
        for left, right in source_spans(normalized):
            target = normalized[left:right]
            reason = text_screen(
                target, grounded=context.get("task") == "narrate_confirmed_outcome"
            )
            if reason:
                rejects[reason] += 1
                continue
            prefix = dict(context)
            if left:
                prefix["earlier_same_source_utterance"] = normalized[:left]
            rendered = dumps(prefix)
            if target in rendered:
                rejects["TARGET_TEXT_ALREADY_IN_INPUT"] += 1
                continue
            if PRIVATE.search(rendered) or UNSAFE.search(rendered):
                rejects["INPUT_PRIVACY_OR_INSTRUCTION_REVIEW"] += 1
                continue
            key = identity([source, unit, left, right])
            previous = db.execute("SELECT rank FROM cases WHERE id=?", (key,)).fetchone()
            if previous and previous[0] >= rank:
                counts["same_source_unit_lower_priority_contexts"] += 1
                ids.append(key)
                continue
            proof = metadata | {
                "source_language": source_language,
                "source_unit": unit,
                "normalized_span": [left, right],
                "original_target": text,
                "curation_version": VERSION,
                "human_reviewed": False,
                "context_sha256": identity(prefix),
            }
            stored_context = prefix
            if source == "CRD3":
                # The immutable A layer already contains this entire transcript.
                # Retain exact source/span/hash references, not eight repeated turns per row.
                proof.pop("original_target")
                proof["source_text_sha256"] = identity(text)
                stored_context = {"materialization": "CRD3_CONTEXT_FROM_PINNED_EPISODE"}
            db.execute(
                "INSERT OR REPLACE INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                (
                    key,
                    source,
                    group,
                    split,
                    unit,
                    rank,
                    packed(stored_context),
                    packed(target),
                    packed(proof),
                    packed(tags),
                ),
            )
            ids.append(key)
        return ids

    ledger = output / "curation-ledger.jsonl.gz"
    if ledger.exists():
        ledger.rename(output / ("curation-ledger-interrupted-" + uuid.uuid4().hex + ".jsonl.gz"))
    with gzip.open(ledger, "wt", encoding="utf-8", compresslevel=6) as stream:
        for number, (member, observations) in enumerate(sorted(groups.items()), 1):
            payload, timeline, expected = roles.execute(
                "SELECT messages,changes,payload_sha256 FROM members WHERE path=?", (member,)
            ).fetchone()
            if hashlib.sha256(payload + timeline).hexdigest() != expected:
                raise ValueError("Role source snapshot changed")
            messages = unpacked(payload)
            records, states = [], {}
            for obs in observations:
                file, line, line_sha, body = original.execute(
                    "SELECT file,line,line_sha,payload FROM observations WHERE id=?", (obs,)
                ).fetchone()
                record = unpacked(body)
                records.append((obs, file, line, line_sha, record))
                for field, state_key in (
                    ("before_state_idx", "combat_state_before"),
                    ("after_state_idx", "combat_state_after"),
                ):
                    index = record.get(field)
                    if type(index) is int and isinstance(record.get(state_key), list):
                        projection = compact_actors({"combat_state_before": record[state_key]})[
                            "before"
                        ]
                        if index in states and states[index] != projection:
                            counts["ambiguous_normalized_state_references"] += 1
                            states[index] = None
                        elif index not in states:
                            states[index] = projection
            group, split = components[member]
            for obs, file, line, line_sha, record in records:
                counts["fireball_source_records"] += 1
                row_ids, why = [], Counter()
                for portion in ("after", "before"):
                    candidates, reasons = linked_dm_targets(record, messages, portion=portion)
                    why.update(reasons)
                    for candidate in candidates:
                        if portion == "before" and not re.search(
                            r"\*[^*]{15,}\*|_[^_]{15,}_|(?m:^\s*>)|[\"“][^\"”]{15,}[\"”]",
                            candidate["target"],
                        ):
                            why["UNCLASSIFIED_BEFORE_TEXT_WITHOUT_EXPLICIT_ROLEPLAY_FRAMING"] += 1
                            continue
                        m = candidate["message"]
                        task = (
                            "narrate_confirmed_outcome"
                            if portion == "after"
                            else "continue_dm_scene"
                        )
                        context = (
                            fireball_context(record, candidate["ordinal"])
                            if portion == "after"
                            else prior_scene(messages, m["index"], states)
                        )
                        tags = (
                            fireball_evidence(record)
                            if portion == "after"
                            else prose_evidence(candidate["target"])
                        )
                        tags["narration"] = "SOURCE_ACCOUNT_MATCHES_EXPLICIT_PRIOR_DM"
                        metadata = {
                            "dataset": "FIREBALL",
                            "revision": "1b363686ed0d681bf8a0eb1e943af75d3716f7c8",
                            "file": file,
                            "file_sha256": file_hashes[file],
                            "line": line,
                            "line_sha256": line_sha,
                            "observation_id": obs,
                            "native_member": member,
                            "raw_message": m,
                            "archive_sha256": role_report["archive_sha256"],
                            "published_portion": portion,
                            "published_ordinal": candidate["ordinal"],
                            "license": "CC-BY-4.0",
                            "task": task,
                            "source_mechanics": (
                                "OBSERVED_AVRAE_NOT_OWNER_RULES_OR_RUNTIME_IMPLEMENTATION"
                            ),
                        }
                        rank = (
                            1000000 + max(record.get("command_idxs", [0]))
                            if portion == "after"
                            else (context["state_index"] or 0)
                        )
                        row_ids += store(
                            "FIREBALL",
                            group,
                            split,
                            member + ":" + str(m["index"]),
                            rank,
                            context,
                            candidate["target"],
                            metadata,
                            tags,
                        )
                rejects.update(why)
                stream.write(
                    dumps(
                        {
                            "source": "FIREBALL",
                            "id": obs,
                            "source_target_candidates": row_ids,
                            "review_reasons": dict(why),
                            "source_preserved": True,
                        }
                    )
                    + "\n"
                )
            if number % 100 == 0:
                db.commit()
                guard()
            if number % 1000 == 0:
                print(
                    dumps(
                        {
                            "native_groups_curated": number,
                            "cases": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                        }
                    ),
                    flush=True,
                )
        original.close()
        roles.close()
        for episode_number, (entry, value) in enumerate(read_sources(crd3_root), 1):
            turns = value["TURNS"]
            episode = Path(entry["path"]).stem
            campaign = episode.split("E", 1)[0]
            if campaign not in {"C1", "C2"}:
                raise ValueError("Unknown reliable campaign grouping")
            group = "CRD3:campaign:" + campaign
            split = "train" if campaign == "C1" else "test"
            for index, turn in enumerate(turns):
                counts["crd3_source_turns"] += 1
                ids, why = [], None
                if turn.get("NAMES") != ["MATT"]:
                    why = "NOT_SINGLE_EXPLICIT_PRIMARY_DM_SPEAKER"
                else:
                    text = " ".join(turn["UTTERANCES"])
                    # Screens are repeated per contiguous chunk; long targets are not truncated.
                    tags = prose_evidence(text) | {
                        "narration": "SOURCE_TRANSCRIBER_LABEL_PRIMARY_DM"
                    }
                    if '"' in text:
                        tags["npc_dialogue"] = "SOURCE_DM_QUOTED_DIALOGUE_CANDIDATE"
                    metadata = {
                        "dataset": "CRD3",
                        "revision": CRD3_REVISION,
                        "file": entry["path"],
                        "file_sha256": entry["sha256"],
                        "turn_index": index,
                        "turn_number": turn.get("NUMBER"),
                        "speaker_evidence": "TRANSCRIBER_NAMES_EXACTLY_MATT_PRIMARY_DM",
                        "license": "CC-BY-SA-4.0",
                        "task": "continue_dm_scene",
                        "source_mechanics": (
                            "UNSTRUCTURED_TRANSCRIPT_NOT_A_VALIDATED_ENGINE_RECEIPT"
                        ),
                    }
                    ids = store(
                        "CRD3",
                        group,
                        split,
                        episode + ":" + str(index),
                        0,
                        crd3_context(turns, index),
                        text,
                        metadata,
                        tags,
                    )
                    if not ids:
                        why = "CHUNKS_RETAINED_IN_SOURCE_OR_REVIEW_NOT_ELIGIBLE_FOR_PRIMARY_POOL"
                stream.write(
                    dumps(
                        {
                            "source": "CRD3",
                            "episode": episode,
                            "turn": index,
                            "source_target_candidates": ids,
                            "reason": why,
                            "source_preserved": True,
                        }
                    )
                    + "\n"
                )
            db.commit()
            guard()
            if episode_number % 20 == 0:
                print(
                    dumps(
                        {
                            "crd3_episodes_curated": episode_number,
                            "cases": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                        }
                    ),
                    flush=True,
                )
        from training.grounded_validation import verify

        _, baseline = verify(baseline_root)
        from training.tokenize_dataset import messages_for

        for split, rows in baseline.items():
            for row in rows:
                key = "reference:" + row["sample_id"]
                metadata = {
                    "dataset": "PROJECT_REFERENCE",
                    "sample_id": row["sample_id"],
                    "source_language": "ru",
                    "reference_row_sha256": identity(row),
                    "source_unit": row["sample_id"],
                    "human_reviewed": False,
                    "synthetic": True,
                    "task": "project_confirmed_outcome",
                }
                db.execute(
                    "INSERT OR REPLACE INTO cases VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        key,
                        "PROJECT_REFERENCE",
                        row["campaign_id"],
                        split,
                        row["sample_id"],
                        0,
                        packed({"messages": messages_for(row)}),
                        packed(row["assistant_reply"]),
                        packed(metadata),
                        dumps(reference_evidence(row)),
                    ),
                )
                counts["synthetic_reference_rows"] += 1
    db.commit()
    report = {
        "schema": "gm-complete-source-candidate-pool-v1",
        "status": "CURATION_COMPLETE_SELECTION_PENDING",
        "counts": dict(counts),
        "review_reasons": dict(rejects),
        "cases": [
            list(row)
            for row in db.execute("SELECT source,split,COUNT(*) FROM cases GROUP BY source,split")
        ],
        "fireball_dm_components": len({v[0] for v in components.values()}),
        "crd3_grouping": "C1_TRAIN_C2_TEST_NO_CROSS_CAMPAIGN_WINDOWS_NO_CRD3_VALIDATION",
        "curation_version": VERSION,
        "human_approved": 0,
        "training_steps": 0,
    }
    db.close()
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def file_digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def bind_job(output, binding, *, resume):
    """A resumed cache must use the same sources and curation policy."""
    job = output / "job.json"
    if job.exists():
        if not resume or json.loads(job.read_text(encoding="utf-8")) != binding:
            raise ValueError("Source pool job differs; choose a new output")
    elif resume and (output / "pool.sqlite").exists():
        raise ValueError("Legacy unbound cache cannot be resumed")
    else:
        job.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in (
        "fireball-root",
        "roles-root",
        "native-map",
        "crd3-root",
        "baseline-root",
        "output",
    ):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    print(
        json.dumps(
            curate(
                a.fireball_root,
                a.roles_root,
                a.native_map,
                a.crd3_root,
                a.baseline_root,
                a.output,
                resume=a.resume,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
