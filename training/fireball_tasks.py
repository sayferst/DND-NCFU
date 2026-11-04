"""Exact Faun candidate encoding for native FIREBALL task views; no training or translation."""

import argparse
import array
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

from training.fireball_observations import database, dumps, unpacked
from training.fireball_readiness import readiness as task_readiness
from training.tokenize_dataset import PinnedFaunTokenizer

SYSTEMS = {
    ("utterance_to_command"): (
        "Return the recorded Avrae commands as JSON, using only the prece"
        "ding context and utterance. Do not execute commands."
    ),
    ("command_to_result"): (
        "Return the observed automation results as JSON. These are bot ou"
        "tputs, not human narration or universal rules."
    ),
    ("observed_transition"): (
        "Return the observed next actor states as JSON, given prior state"
        "s and confirmed execution results. Preserve unknown values."
    ),
    ("grounded_utterance"): (
        "Return the source-linked subsequent utterances as JSON given the"
        " confirmed results. Speaker roles are not verified as Dungeon Ma"
        "ster."
    ),
    ("dialogue_sequence"): (
        "Continue the source dialogue with its recorded next utterances a"
        "s JSON. Do not infer hidden speaker roles."
    ),
    ("negative_outcome_candidate"): (
        "Return the recorded automation response as JSON. Error or failed"
        "-action interpretation requires contextual review."
    ),
}
PROFILES = (2048, 4096, 8192, 16384, 32768, 65536, 131072)


def messages(task, inputs):
    # Escapes are reversible JSON serialization, not edits to the canonical source.
    content = json.dumps(inputs, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")
    return [{"role": "system", "content": SYSTEMS[task]}, {"role": "user", "content": content}]


def encode_view(tokenizer, task, inputs, target):
    user = messages(task, inputs)
    answer = json.dumps(target, ensure_ascii=False).replace("<", "\\u003c")
    prefix = tokenizer.apply_chat_template(
        user, tokenize=True, add_generation_prompt=True, return_dict=False
    )
    complete = tokenizer.apply_chat_template(
        user + [{"role": "assistant", "content": answer}],
        tokenize=True,
        add_generation_prompt=False,
        return_dict=False,
    )
    if complete[: len(prefix)] != prefix:
        raise ValueError("ChatML prefix mismatch: no safe loss mask")
    target_ids = complete[len(prefix) :]
    if not target_ids:
        raise ValueError("Empty supervised target")
    return user, answer, prefix, target_ids


def token_hash(prefix, target):
    # Portable hash of the exact IDs and mask boundary, without allocating labels twice.
    ids = array.array("I", prefix + target)
    if sys.byteorder != "little":
        ids.byteswap()
    return hashlib.sha256(len(prefix).to_bytes(8, "little") + ids.tobytes()).hexdigest()


def render_view(tokenizer, task, inputs, target):
    user = messages(task, inputs)
    answer = json.dumps(target, ensure_ascii=False).replace("<", "\\u003c")
    prefix = tokenizer.apply_chat_template(
        user, tokenize=False, add_generation_prompt=True, return_dict=False
    )
    full = tokenizer.apply_chat_template(
        user + [{"role": "assistant", "content": answer}],
        tokenize=False,
        add_generation_prompt=False,
        return_dict=False,
    )
    return user, answer, prefix, full


def candidate_record(row, metadata, user=None, answer=None):
    if user is None:
        user = messages(row[2], unpacked(row[5]))
    if answer is None:
        answer = json.dumps(unpacked(row[6]), ensure_ascii=False).replace("<", "\\u003c")
    return {
        "schema": "fireball-native-task-candidate-v1",
        "id": row[0],
        "source_observation_id": row[1],
        "task": row[2],
        "group_id": row[3],
        "split": row[4],
        "messages": user + [{"role": "assistant", "content": answer}],
        "tokens": {"input": metadata[3], "target": metadata[4], "total": metadata[5]},
        "suggested_profile": metadata[1],
        "readiness": metadata[2],
        "human_approved": False,
        "privacy": "AUTOMATIC_REDACTIONS_REQUIRES_REVIEW",
        "rights": "SOURCE_CC_BY_4_0_ATTRIBUTION_REQUIRED_CONTENT_REVIEW_PENDING",
        "target_kind": row[7].replace("observed_human_command", "observed_command_role_unverified"),
        "runtime_compatibility": "NOT_ASSESSED_NOT_REQUIRED",
        "source_language": "ORIGINAL_NOT_TRANSLATED_HEURISTIC_IN_OBSERVATION",
        "source_link": "observations.sqlite:observations:" + row[1],
        "token_hash": metadata[6],
        "loss_mask": {"prompt": -100, "target": "ALL_TARGET_IDS"},
        "completion": "PINNED_CHATML_IM_END_NEWLINE_NO_EXTRA_EOS",
    }


def encode_batch(tokenizer, rows):
    rendered = [render_view(tokenizer, r[2], unpacked(r[5]), unpacked(r[6])) for r in rows]
    encoded = tokenizer.backend.encode_batch(
        [text for _, _, prefix, full in rendered for text in (prefix, full)],
        add_special_tokens=False,
    )
    ending = tokenizer.backend.encode("<|im_end|>\n", add_special_tokens=False).ids
    results = []
    for i, (row, (user, answer, _, _)) in enumerate(zip(rows, rendered, strict=True)):
        prefix, complete = encoded[2 * i].ids, encoded[2 * i + 1].ids
        if complete[: len(prefix)] != prefix or complete[-len(ending) :] != ending:
            raise ValueError("Unsafe Faun prefix or completion terminator")
        target = complete[len(prefix) :]
        if not target:
            raise ValueError("Empty target")
        length = len(complete)
        profile = next((size for size in PROFILES if length <= size), None)
        status = "CANDIDATE_PENDING_REVIEW" if profile else "LONG_CONTEXT_REVIEW_RETAINED"
        native_readiness = task_readiness(row[2], unpacked(row[5]))
        if native_readiness.startswith("OBSERVATION_"):
            status = native_readiness
        sha = token_hash(prefix, target)
        metadata = (row[0], profile, status, len(prefix), len(target), length, sha)
        record = candidate_record(row, metadata, user, answer)
        results.append((record, metadata))
    return results


def export(root, tokenizer_path, output, *, batch_size=64):
    """Atomic resumable shards. Each SELECT is closed before any metadata write."""
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    db = database(root)
    db.execute(
        "CREATE TABLE IF NOT EXISTS export_shards(name TEXT PRIMARY KEY,first_id TEXT,"
        "last_id TEXT,rows INTEGER,sha256 TEXT,bytes INTEGER)"
    )
    config = json.loads(
        (Path(__file__).parent / "configs/faun_qlora_v1.json").read_text(encoding="utf-8")
    )
    tokenizer = PinnedFaunTokenizer(tokenizer_path, config)
    state = {
        "tokenizer_fingerprint": tokenizer.fingerprint,
        "batch_size": batch_size,
        "schema": "fireball-native-task-candidate-v1",
        "systems_sha256": hashlib.sha256(dumps(SYSTEMS).encode()).hexdigest(),
    }
    binding = output / "job.json"
    if binding.exists():
        if json.loads(binding.read_text(encoding="utf-8")) != state:
            raise ValueError("Refusing changed tokenizer or export job on resume")
    else:
        binding.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    saved = db.execute("SELECT name,last_id,sha256 FROM export_shards ORDER BY last_id").fetchall()
    for name, _, sha in saved:
        path = output / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("Previously completed export shard changed: " + name)
    last = saved[-1][1] if saved else ""
    seen = db.execute("SELECT COUNT(*) FROM exported").fetchone()[0]
    batch_index = len(saved)
    tasks = tuple(SYSTEMS)
    placeholders = ",".join("?" for _ in tasks)
    while True:
        rows = db.execute(
            "SELECT id,observation_id,task,group_id,split,input,target,target_kind FROM views "
            f"WHERE id>? AND task IN ({placeholders}) ORDER BY id LIMIT ?",
            (last, *tasks, batch_size),
        ).fetchall()
        if not rows:
            break
        values = encode_batch(tokenizer, rows)
        name = f"candidates-{batch_index:06d}.jsonl.gz"
        dest = output / name
        temp = dest.with_suffix(dest.suffix + ".partial")
        # A crash after rename but before commit is safely regenerated from the same rows.
        with gzip.open(temp, "wt", encoding="utf-8", compresslevel=3) as stream:
            for record, _ in values:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        sha = hashlib.sha256(temp.read_bytes()).hexdigest()
        size = temp.stat().st_size
        os.replace(temp, dest)
        db.executemany(
            "INSERT OR REPLACE INTO exported VALUES(?,?,?,?,?,?,?)",
            [metadata for _, metadata in values],
        )
        db.execute(
            "INSERT INTO export_shards VALUES(?,?,?,?,?,?)",
            (name, rows[0][0], rows[-1][0], len(rows), sha, size),
        )
        db.commit()
        last = rows[-1][0]
        seen += len(rows)
        batch_index += 1
        if batch_index % 100 == 0:
            print(dumps({"encoded_candidates": seen, "shards": batch_index}), flush=True)
    counts = [
        dict(
            zip(
                (
                    "task",
                    "split",
                    "profile",
                    "status",
                    "n",
                    "tokens",
                    "supervised_tokens",
                    "min_length",
                    "max_length",
                ),
                row,
                strict=True,
            )
        )
        for row in db.execute(
            "SELECT v.task,v.split,e.profile,e.status,COUNT(*),SUM(e.total_tokens),"
            "SUM(e.target_tokens),"
            "MIN(e.total_tokens),MAX(e.total_tokens) FROM exported e JOIN views v ON v.id=e.id "
            "GROUP BY v.task,v.split,e.profile,e.status"
        )
    ]
    distributions = {}
    for task in SYSTEMS:
        for split in ("train", "val", "test"):
            values = [
                row[0]
                for row in db.execute(
                    "SELECT e.total_tokens FROM exported e JOIN views v ON v.id=e.id "
                    "WHERE v.task=? AND v.split=? AND e.total_tokens IS NOT NULL "
                    "ORDER BY e.total_tokens",
                    (task, split),
                )
            ]
            if values:
                distributions[task + ":" + split] = {
                    "n": len(values),
                    "min": values[0],
                    "max": values[-1],
                    **{
                        label: values[int((len(values) - 1) * q)]
                        for label, q in (("p50", 0.50), ("p90", 0.90), ("p95", 0.95), ("p99", 0.99))
                    },
                }
    summary = {
        "schema": "fireball-native-task-tokenization-v1",
        "encoded_candidates": seen,
        "counts": counts,
        "length_distributions": distributions,
        "tokenizer_fingerprint": tokenizer.fingerprint,
        "full_context_retained_in_layers_A_B_C": True,
        "silently_dropped_targets": 0,
        "training_steps": 0,
        "human_approved": 0,
        "train_admitted": 0,
        "weights_loaded": False,
        "profile_limits": list(PROFILES),
        "model_metadata_max_positions": 1024000,
        "profiles_are_not_GPU_capacity_claims": True,
        "completion": "ChatML im_end plus newline; config EOS </s> is not appended by template",
        "mask": "-100 for entire prompt; every assistant target token supervised",
        "token_hash_format": "SHA256(uint64le(prompt_length) + uint32le(all_token_ids))",
        "files": {
            name: {"bytes": size, "sha256": sha, "rows": n}
            for name, sha, size, n in db.execute(
                "SELECT name,sha256,bytes,rows FROM export_shards ORDER BY name"
            )
        },
    }
    (output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for task in SYSTEMS:
        value = config | {
            "dataset_policy": "fireball-native-candidates-v1",
            "task": task,
            "candidate_directory": ".",
            "status": "BLOCKED_REVIEW_NOT_TRAIN_ADMITTED",
            "model_path": "models/faun-reviewed-base",
            "output": "artifacts/fireball-" + task,
            "max_length": 2048,
            "long_context_profiles": list(PROFILES),
            "review_required": True,
            "train_admitted": 0,
            "training_started": False,
            "dataset": "data/fireball-native-reviewed-ONLY",
            "purpose": "TASK_CONFIGURATION_CANDIDATE_REVIEW_REQUIRED",
            "completion_token": "<|im_end|>",
            "generation_stop_token_ids": [2, 131072],
            "loss": "assistant_only",
        }
        (output / (task + "-config.json")).write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )
    db.close()
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--tokenizer", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(export(a.root, a.tokenizer, a.output), indent=2))


if __name__ == "__main__":
    main()
