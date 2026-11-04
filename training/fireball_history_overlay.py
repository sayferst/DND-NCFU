"""Repair HF dialogue context with verified native-combat correspondences, preserving the base."""

import argparse
import gzip
import hashlib
import json
from collections import Counter, deque
from pathlib import Path

from training.fireball_observations import (
    database,
    indices,
    paged_observations,
    scrub,
    trusted_history_scope,
    unpacked,
)
from training.fireball_readiness import readiness
from training.fireball_tasks import PROFILES, encode_view, token_hash
from training.tokenize_dataset import PinnedFaunTokenizer


def corrected_dialogues(db, native_groups):
    history = deque(maxlen=5)
    current = None
    for file, _line, identity, payload, status in paged_observations(db, "o.id,o.payload,o.status"):
        value = unpacked(payload)
        scope = trusted_history_scope(file, identity, value, native_groups)
        if current != (file, scope) or scope is None:
            history.clear()
            current = (file, scope)
        starts = indices(value, "before_idxs")
        if type(value.get("before_state_idx")) is int:
            starts.append(value["before_state_idx"])
        start = min(starts) if starts else None
        safe = [
            v for v in history if start is not None and v["end"] is not None and v["end"] < start
        ]
        row = db.execute(
            "SELECT id,input,target FROM views WHERE observation_id=? AND task='dialogue_sequence'",
            (identity,),
        ).fetchone()
        if row:
            inputs = scrub({"previous_turns": [v["value"] for v in safe]})
            if inputs != unpacked(row[1]):
                yield {
                    "view_id": row[0],
                    "source_observation_id": identity,
                    "base_input_sha256": hashlib.sha256(row[1]).hexdigest(),
                    "input": inputs,
                    "target": unpacked(row[2]),
                    "native_group": scope,
                    "history_source_ids": [v["id"] for v in safe],
                    "readiness": readiness("dialogue_sequence", inputs),
                }
        if status == "PRESERVED":
            ends = [
                v for k in ("command_idxs", "after_idxs", "embed_idxs") for v in indices(value, k)
            ]
            if type(value.get("after_state_idx")) is int:
                ends.append(value["after_state_idx"])
            history.append(
                {
                    "id": identity,
                    "end": max(ends) if ends else None,
                    "value": {
                        k: value[k] for k in ("before_utterances", "commands_norm") if k in value
                    },
                }
            )


def build(root, group_map, tokenizer_root, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with gzip.open(group_map, "rt", encoding="utf-8") as f:
        groups = {v["hf_observation_id"]: v["native_group"] for v in map(json.loads, f)}
    config = json.loads(
        (Path(__file__).parent / "configs/faun_qlora_v1.json").read_text(encoding="utf-8")
    )
    tokenizer = PinnedFaunTokenizer(tokenizer_root, config)
    db = database(root)
    counts = Counter()
    n = 0
    native_cross = 0
    dest = output / "history-overlay.jsonl.gz"
    with gzip.open(dest, "wt", encoding="utf-8", compresslevel=6) as f:
        for patch in corrected_dialogues(db, groups):
            for previous in patch["history_source_ids"]:
                if (
                    patch["source_observation_id"] in groups
                    and groups.get(previous) != groups[patch["source_observation_id"]]
                ):
                    native_cross += 1
            _, _, prefix, target = encode_view(
                tokenizer, "dialogue_sequence", patch["input"], patch["target"]
            )
            size = len(prefix) + len(target)
            profile = next((v for v in PROFILES if size <= v), None)
            state = (
                patch["readiness"]
                if patch["readiness"].startswith("OBSERVATION_")
                else "CANDIDATE_PENDING_REVIEW"
            )
            patch["token_metadata"] = [
                patch["view_id"],
                profile,
                state,
                len(prefix),
                len(target),
                size,
                token_hash(prefix, target),
            ]
            patch["human_approved"] = False
            patch["train_admitted"] = False
            f.write(json.dumps(patch, ensure_ascii=True) + "\n")
            n += 1
            counts[state] += 1
            if n % 1000 == 0:
                print(json.dumps({"repaired_dialogue_views": n}), flush=True)
    db.close()
    if native_cross:
        raise ValueError("Corrected history still crosses native combats")
    result = {
        "schema": "fireball-native-history-overlay-v1",
        "status": "COMPLETE",
        "patches": n,
        "states": dict(counts),
        "cross_native_combat_links_in_corrected_history": native_cross,
        "tokenizer_fingerprint": tokenizer.fingerprint,
        "base_modified": False,
        "targets_modified": False,
        "silently_truncated_targets": 0,
        "human_approved": 0,
        "train_admitted": 0,
        "training_steps": 0,
        "overlay_sha256": file_sha(dest),
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def load_overlay(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    path = folder / "history-overlay.jsonl.gz"
    if manifest["status"] != "COMPLETE" or file_sha(path) != manifest["overlay_sha256"]:
        raise ValueError("Incomplete or changed history correction overlay")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    if len(rows) != manifest["patches"] or len({v["view_id"] for v in rows}) != len(rows):
        raise ValueError("Missing/duplicate overlay row")
    return {r["view_id"]: r for r in rows}, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--group-map", type=Path, required=True)
    p.add_argument("--tokenizer", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.root, a.group_map, a.tokenizer, a.output), indent=2))


if __name__ == "__main__":
    main()
