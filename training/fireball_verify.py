"""Independent streaming byte/field/line accounting against every immutable source."""

import argparse
import base64
import hashlib
import json
from pathlib import Path

from training.fireball_observations import (
    TASKS,
    database,
    dumps,
    indices,
    paged_observations,
    strict_source_json,
    unpacked,
)


def verify(root):
    root = Path(root)
    db = database(root)
    errors = []
    lines = 0
    files = 0
    quarantine = 0
    for file, expected_sha, expected_lines in db.execute(
        "SELECT * FROM ingested ORDER BY file"
    ).fetchall():
        path = (
            root / "primary/FIREBALL" / file[5:]
            if file.startswith("DEMO/")
            else root / "originals" / file
        )
        h = hashlib.sha256()
        count = 0
        try:
            with path.open("rb") as stream:
                for count, raw in enumerate(stream, 1):
                    h.update(raw)
                    lines += 1
                    row = db.execute(
                        "SELECT line_sha,payload,status FROM observations WHERE file=? AND line=?",
                        (file, count),
                    ).fetchone()
                    if row is None:
                        errors.append(
                            {"file": file, "line": count, "reason": "MISSING_CANONICAL_RECORD"}
                        )
                        continue
                    sha, payload, status = row
                    if hashlib.sha256(raw).hexdigest() != sha:
                        errors.append(
                            {"file": file, "line": count, "reason": "SOURCE_LINE_SHA_CHANGED"}
                        )
                    if status == "QUARANTINE":
                        quarantine += 1
                        if base64.b64decode(unpacked(payload)["raw_line_base64"]) != raw:
                            errors.append(
                                {"file": file, "line": count, "reason": "QUARANTINE_BYTES_LOST"}
                            )
                    else:
                        try:
                            value = strict_source_json(raw)
                            if dumps(value) != dumps(unpacked(payload)):
                                errors.append(
                                    {
                                        "file": file,
                                        "line": count,
                                        "reason": "CANONICAL_FIELD_OR_VALUE_LOSS",
                                    }
                                )
                        except Exception as exc:
                            errors.append(
                                {
                                    "file": file,
                                    "line": count,
                                    "reason": "UNQUARANTINED_PARSE_ERROR",
                                    "detail": str(exc),
                                }
                            )
            if h.hexdigest() != expected_sha or count != expected_lines:
                errors.append({"file": file, "reason": "FILE_SHA_OR_LINE_COUNT_CHANGED"})
            files += 1
        except OSError as exc:
            errors.append({"file": file, "reason": "UNREADABLE_SOURCE", "detail": str(exc)})
        if files % 50 == 0:
            print(
                json.dumps({"verified_files": files, "lines": lines, "errors": len(errors)}),
                flush=True,
            )
    total = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    if lines != total:
        errors.append(
            {
                "reason": "UNACCOUNTED_OR_EXTRA_CANONICAL_RECORDS",
                "source_lines": lines,
                "canonical": total,
            }
        )
    expected = json.loads((root / "tree-comparison.json").read_text(encoding="utf-8"))
    downloaded = db.execute(
        "SELECT COUNT(*) FROM ingested WHERE file LIKE 'filtered/%'"
    ).fetchone()[0]
    if downloaded != expected["tree_files"]:
        errors.append({"reason": "INCOMPLETE_FILTERED_TREE"})
    result = {
        "schema": "fireball-independent-lossless-check-v1",
        "status": "PASS" if not errors else "FAILED",
        "verified_files": files,
        "verified_source_lines": lines,
        "canonical_records": total,
        "quarantined_lines": quarantine,
        "errors": errors,
        "missing_fields": 0 if not errors else None,
        "all_filtered_files": downloaded,
        "expected_filtered_files": expected["tree_files"],
    }
    (root / "lossless-check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    db.close()
    return result


def verify_tasks(root):
    db = database(root)
    bad_dispositions = db.execute(
        "SELECT COUNT(*) FROM observations o WHERE (SELECT COUNT(*) FROM dispositions d "
        "WHERE d.observation_id=o.id)!=?",
        (len(TASKS),),
    ).fetchone()[0]
    marks = ",".join("?" for _ in TASKS)
    invalid_tasks = db.execute(
        f"SELECT COUNT(*) FROM dispositions WHERE task NOT IN ({marks})", TASKS
    ).fetchone()[0]
    missing_views = db.execute(
        "SELECT COUNT(*) FROM dispositions d LEFT JOIN views v "
        "ON v.observation_id=d.observation_id "
        "AND v.task=d.task WHERE d.status IN ('CANDIDATE','OBSERVATION_ONLY') AND v.id IS NULL"
    ).fetchone()[0]
    orphan_views = db.execute(
        "SELECT COUNT(*) FROM views v LEFT JOIN dispositions d "
        "ON d.observation_id=v.observation_id "
        "AND d.task=v.task WHERE d.status IS NULL OR d.status='UNAVAILABLE'"
    ).fetchone()[0]
    wrong_splits = db.execute(
        "SELECT COUNT(*) FROM views v JOIN observations o ON o.id=v.observation_id "
        "JOIN split_map s ON s.group_id=o.group_id WHERE v.split!=s.split OR v.group_id!=o.group_id"
    ).fetchone()[0]
    times = {}
    for _file, _line, identity, payload, status in paged_observations(
        db, "o.id,o.payload,o.status"
    ):
        if status != "PRESERVED":
            continue
        value = unpacked(payload)
        starts = indices(value, "before_idxs")
        if type(value.get("before_state_idx")) is int:
            starts.append(value["before_state_idx"])
        ends = [v for k in ("command_idxs", "after_idxs", "embed_idxs") for v in indices(value, k)]
        if type(value.get("after_state_idx")) is int:
            ends.append(value["after_state_idx"])
        times[identity] = (min(starts) if starts else None, max(ends) if ends else None)
    temporal = 0
    for current, previous in db.execute(
        "SELECT v.observation_id,l.related_observation FROM view_links l "
        "JOIN views v ON v.id=l.view_id"
    ):
        start = times.get(current, (None, None))[0]
        end = times.get(previous, (None, None))[1]
        if start is None or end is None or end >= start:
            temporal += 1
    future_keys = 0
    last = ""
    while rows := db.execute(
        "SELECT id,input FROM views WHERE task='utterance_to_command' "
        "AND id>? ORDER BY id LIMIT 256",
        (last,),
    ).fetchall():
        for _identity, payload in rows:
            if set(unpacked(payload)) - {
                "combat_state_before",
                "current_actor",
                "utterance_history",
                "before_utterances",
            }:
                future_keys += 1
        last = rows[-1][0]
    failures = {
        "source_rows_missing_task_decisions": bad_dispositions,
        "unknown_task_names": invalid_tasks,
        "eligible_decisions_missing_view": missing_views,
        "views_missing_eligible_decision": orphan_views,
        "split_or_group_mismatch": wrong_splits,
        "unsafe_history_temporal_links": temporal,
        "command_future_input_fields": future_keys,
    }
    result = {
        "schema": "fireball-independent-task-check-v1",
        "status": "PASS" if not any(failures.values()) else "FAILED",
        "failures": failures,
        "history_order_evidence": (
            "strict original event indices, not a full raw timestamp reconstruction"
        ),
        "human_approved": 0,
        "train_admitted": 0,
    }
    db.close()
    (Path(root) / "task-integrity-check.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--tasks", action="store_true")
    a = p.parse_args()
    r = verify_tasks(a.root) if a.tasks else verify(a.root)
    print(json.dumps(r, indent=2))
    if r["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
