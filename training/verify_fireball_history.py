"""Independent exhaustive correction validation; requires the CPU tokenizer stack, no weights."""

import argparse
import gzip
import hashlib
import json
import sqlite3
import zlib
from pathlib import Path

from transformers import AutoTokenizer

from training.fireball_history_overlay import load_overlay
from training.fireball_tasks import encode_view, token_hash

p = argparse.ArgumentParser(
    description="Independent full AutoTokenizer verification of corrected history"
)
p.add_argument("--root", type=Path, required=True)
p.add_argument("--overlay", type=Path, required=True)
p.add_argument("--group-map", type=Path, required=True)
p.add_argument("--tokenizer", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
patches, m = load_overlay(a.overlay)
with gzip.open(a.group_map, "rt", encoding="utf-8") as f:
    groups = {v["hf_observation_id"]: v["native_group"] for v in map(json.loads, f)}
db = sqlite3.connect(a.root / "observations.sqlite")
for id, _file in db.execute(
    "SELECT id,file FROM observations WHERE file='DEMO/filtered_triples.jsonl'"
):
    groups[id] = "pinned-primary-demo"
oldlinks = {}
cross_before = 0
cross_after = 0
missing = 0
new_links = 0
for view, current, previous in db.execute(
    "SELECT l.view_id,v.observation_id,l.related_observation FROM view_links l "
    "JOIN views v ON v.id=l.view_id"
):
    if view in patches:
        oldlinks.setdefault(view, set()).add(previous)
    if groups.get(current) != groups.get(previous):
        cross_before += 1
    if view not in patches:
        if groups.get(current) != groups.get(previous):
            cross_after += 1
        if current not in groups or previous not in groups:
            missing += 1
for p in patches.values():
    if not set(p["history_source_ids"]) <= oldlinks.get(p["view_id"], set()):
        raise ValueError("Unexpected new context outside verified temporal links")
    for prev in p["history_source_ids"]:
        if groups.get(p["source_observation_id"]) != groups.get(prev):
            cross_after += 1
        new_links += 1
if cross_after or missing:
    raise ValueError("Corrected corpus has unsafe source scope")
tok = AutoTokenizer.from_pretrained(
    str(a.tokenizer), local_files_only=True, trust_remote_code=False
)
n = 0
delta = 0
for identity, p in patches.items():
    oldinput, target, oldlen = db.execute(
        "SELECT v.input,v.target,e.total_tokens FROM views v JOIN exported e ON e.id=v.id "
        "WHERE v.id=?",
        (identity,),
    ).fetchone()
    assert hashlib.sha256(oldinput).hexdigest() == p["base_input_sha256"]
    assert json.loads(zlib.decompress(target)) == p["target"]
    _, _, prefix, answer = encode_view(tok, "dialogue_sequence", p["input"], p["target"])
    metadata = p["token_metadata"]
    assert [len(prefix), len(answer), len(prefix) + len(answer)] == metadata[3:6]
    assert token_hash(prefix, answer) == metadata[6]
    n += 1
    delta += len(prefix) + len(answer) - oldlen
    if n % 1000 == 0:
        print(json.dumps({"official_AutoTokenizer_verified_corrections": n}), flush=True)
report = {
    "schema": "fireball-native-history-correction-independent-verification-v1",
    "status": "PASS",
    "corrected_views": n,
    "cross_native_links_before": cross_before,
    "cross_native_links_after": cross_after,
    "unresolved_links_after": missing,
    "new_history_links_are_subset_of_previously_checked_temporal_links": True,
    "all_corrected_targets_equal_base": True,
    "official_AutoTokenizer_parity_corrections": n,
    "token_delta": delta,
    "base_modified": False,
    "model_weights_loaded": False,
    "training_steps": 0,
}
a.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
