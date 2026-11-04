"""Full per-source ledgers and review queues, kept outside Git with the large corpus."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

from training.fireball_archive import file_digests
from training.fireball_observations import database, paged_observations


def manifests(root):
    root = Path(root)
    db = database(root)
    sources = dict(db.execute("SELECT file,payload FROM source_metadata"))
    ledger = root / "source-record-ledger.csv.gz"
    headers = [
        "observation_id",
        "revision",
        "source_file",
        "line_one_based",
        "line_sha256",
        "group_id",
        "split",
        "event_type",
        "source_role",
        "role_confidence",
        "language_heuristic",
        "preservation",
        "parse_reason",
        "task_dispositions_json",
        "rights",
        "privacy",
        "runtime",
        "human_approved",
    ]
    with gzip.open(ledger, "wt", encoding="utf-8", newline="", compresslevel=6) as out:
        writer = csv.writer(out)
        writer.writerow(headers)
        for (
            file,
            line,
            identity,
            sha,
            group,
            split,
            kind,
            role,
            confidence,
            lang,
            status,
            reason,
        ) in paged_observations(
            db,
            "o.id,o.line_sha,o.group_id,s.split,o.kind,o.role,o.confidence,o.language,o.status,o.reason",
            "JOIN split_map s ON s.group_id=o.group_id",
        ):
            decisions = {
                t: {"status": s, "reason": r}
                for t, s, r in db.execute(
                    "SELECT task,status,reason FROM dispositions "
                    "WHERE observation_id=? ORDER BY task",
                    (identity,),
                ).fetchall()
            }
            writer.writerow(
                [
                    identity,
                    json.loads(sources[file])["revision"],
                    file,
                    line,
                    sha,
                    group,
                    split,
                    kind,
                    role,
                    confidence,
                    lang,
                    status,
                    reason,
                    json.dumps(decisions, ensure_ascii=False),
                    "CC-BY-4.0_CONTENT_REVIEW_PENDING",
                    "LOCAL_RESTRICTED",
                    "NOT_ASSESSED_NOT_REQUIRED",
                    False,
                ]
            )
    queue = root / "task-review-queue.csv.gz"
    with gzip.open(queue, "wt", encoding="utf-8", newline="", compresslevel=6) as out:
        writer = csv.writer(out)
        writer.writerow(
            [
                "view_id",
                "source_observation_id",
                "task",
                "split",
                "target_kind",
                "readiness",
                "privacy",
                "token_status",
                "profile",
                "tokens",
                "human_approved",
                "train_admitted",
            ]
        )
        last = ""
        while rows := db.execute(
            "SELECT v.id,v.observation_id,v.task,v.split,v.target_kind,v.readiness,v.privacy,"
            "e.status,e.profile,e.total_tokens FROM views v LEFT JOIN exported e ON e.id=v.id "
            "WHERE v.id>? ORDER BY v.id LIMIT 256",
            (last,),
        ).fetchall():
            for row in rows:
                writer.writerow([*row, False, False])
            last = rows[-1][0]
    vocabulary = root / "entity-surfaces.csv.gz"
    with gzip.open(vocabulary, "wt", encoding="utf-8", newline="", compresslevel=6) as out:
        writer = csv.writer(out)
        writer.writerow(
            [
                "kind",
                "surface",
                "field_occurrences_not_unique_events",
                "first_observation_id",
                "first_path",
                "definition_status",
                "runtime_support",
            ]
        )
        for row in db.execute("SELECT * FROM entity_inventory ORDER BY kind,surface"):
            writer.writerow(
                [*row, "UNKNOWN_NOT_CLASSIFIED_NO_DEFINITION_INFERRED", "UNASSESSED_NOT_REQUIRED"]
            )
    files = []
    for relative, payload in sources.items():
        meta = json.loads(payload)
        path = (
            root / "primary/FIREBALL" / relative[5:]
            if relative.startswith("DEMO/")
            else root / "originals" / relative
        )
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": meta["file_sha256"],
                "lines": meta["lines"],
                "revision": meta["revision"],
                "url": meta["source_url"],
                "hf_shard_key": Path(relative).stem if relative.startswith("filtered/") else None,
                "group_evidence": (
                    "HF shard may contain multiple native combats; use native raw correspondence"
                    if relative.startswith("filtered/")
                    else "primary README: both demonstration files are one combat"
                ),
            }
        )
    primaries = []
    for path in sorted((root / "primary").rglob("*")):
        if path.is_file():
            size, sha, blob = file_digests(path)
            primaries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": size,
                    "sha256": sha,
                    "git_blob_sha1": blob,
                }
            )
    release_tree = []
    inventory = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    for entry in inventory["entries"]:
        record = {
            "path": entry["path"],
            "bytes": entry["size"],
            "git_oid": entry.get("oid"),
            "type": entry["type"],
        }
        if entry["type"] == "directory":
            record["status"] = "DIRECTORY_NOT_A_DATA_FILE"
        elif entry["path"].startswith("filtered/"):
            record["status"] = "DOWNLOADED_VERIFIED_AND_EVERY_LINE_ACCOUNTED"
        elif (root / entry["path"]).is_file():
            size, sha, blob = file_digests(root / entry["path"])
            record.update(
                status="PINNED_METADATA_SNAPSHOTTED_NOT_EXECUTED",
                actual_bytes=size,
                sha256=sha,
                verified_git_blob=blob,
            )
        else:
            record["status"] = "DISCOVERED_NON_DATA_GIT_METADATA_NOT_DOWNLOADED"
        release_tree.append(record)
    result = {
        "schema": "fireball-all-downloaded-source-files-v1",
        "source_files": files,
        "all_discovered_hf_entries": release_tree,
        "primary_evidence_files": primaries,
        "raw_release": "NOT_DOWNLOADED_HTTP_403_FROM_THIS_ENVIRONMENT",
        "ledgers": {
            p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in (ledger, queue, vocabulary)
        },
        "record_counts_are_not_task_view_counts": True,
        "approvals": {"human_approved": 0, "train_admitted": 0},
    }
    (root / "source-manifest.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    db.close()
    return {"files": len(files), "primary_files": len(primaries), "ledgers": result["ledgers"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(manifests(a.root), indent=2))


if __name__ == "__main__":
    main()
