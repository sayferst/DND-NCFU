"""Recreate all task exports from the complete observation DB, without loading a tokenizer."""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from training.fireball_observations import database, unpacked
from training.fireball_tasks import SYSTEMS, candidate_record


def materialize(root, output):
    db = database(root)
    predictive = tuple(SYSTEMS)
    marks = ",".join("?" for _ in predictive)
    expected = db.execute(
        f"SELECT COUNT(*) FROM views WHERE task IN ({marks})", predictive
    ).fetchone()[0]
    actual = db.execute("SELECT COUNT(*) FROM exported").fetchone()[0]
    if expected != actual:
        db.close()
        raise ValueError("Token ledger incomplete; finish exact tokenization first")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    handles = {}
    counts = Counter()
    last = ""
    try:
        while rows := db.execute(
            "SELECT v.id,v.observation_id,v.task,v.group_id,v.split,v.input,v.target,v.target_kind,"
            "e.id,e.profile,e.status,e.input_tokens,e.target_tokens,e.total_tokens,e.encoded_sha "
            "FROM views v LEFT JOIN exported e ON e.id=v.id WHERE v.id>? ORDER BY v.id LIMIT 128",
            (last,),
        ).fetchall():
            for row in rows:
                if row[2] in SYSTEMS:
                    if row[8] is None:
                        raise ValueError("Predictive task has no token ledger record")
                    record = candidate_record(row[:8], row[8:])
                    profile = row[9] or "long-retained"
                else:
                    profile = "observation-only"
                    record = {
                        "schema": "fireball-observation-view-v1",
                        "id": row[0],
                        "source_observation_id": row[1],
                        "task": row[2],
                        "group_id": row[3],
                        "split": row[4],
                        "input": unpacked(row[5]),
                        "observed": unpacked(row[6]),
                        "target_kind": row[7],
                        "readiness": "OBSERVATION_NOT_SFT",
                        "human_approved": False,
                        "train_admitted": False,
                        "privacy": "LOCAL_RESTRICTED_PENDING_REVIEW",
                    }
                name = f"{row[2]}-{row[4]}-{profile}.jsonl.gz"
                if name not in handles:
                    handles[name] = gzip.open(
                        output / name, "wt", encoding="utf-8", compresslevel=6
                    )
                handles[name].write(json.dumps(record, ensure_ascii=True) + "\n")
                counts[row[2]] += 1
            last = rows[-1][0]
    finally:
        for handle in handles.values():
            handle.close()
        db.close()
    result = {
        "schema": "fireball-materialized-views-v1",
        "views": dict(counts),
        "tokenized_predictive_views": actual,
        "new_tokenization": False,
        "human_approved": 0,
        "train_admitted": 0,
        "training_steps": 0,
        "source": "Full observations.sqlite; all source observations and task cards preserved",
        "files": {
            p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(output.glob("*.gz"))
        },
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = materialize(a.root, a.output)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
