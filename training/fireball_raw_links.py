"""Resolve native filtered references against the full raw index; HF joins stay candidates."""

import argparse
import gzip
import hashlib
import json
import sqlite3
import zlib
from collections import Counter, defaultdict
from pathlib import Path


def link_record(record, events):
    links = []
    for field, values in record["refs"].items():
        values = values if isinstance(values, list) else [values]
        for ordinal, index in enumerate(values):
            link = {
                "field": field,
                "ordinal": ordinal,
                "native_index": index,
                "status": "INDEX_UNAVAILABLE",
                "role": "unknown",
            }
            if type(index) is int and 0 <= index < len(events):
                kind, role, evidence, author = events[index]
                expected = (
                    "message"
                    if field in {"before_idxs", "after_idxs", "embed_idxs"}
                    else (
                        "combat_state_update"
                        if field in {"before_state_idx", "after_state_idx"}
                        else None
                    )
                )
                valid = kind != "QUARANTINE" and (expected is None or expected == kind)
                link.update(
                    event_type=kind,
                    role=role,
                    role_evidence=evidence,
                    author_id=author,
                    status="INDEX_AND_TYPE_CONFIRMED" if valid else "INDEX_TYPE_REVIEW",
                )
            links.append(link)
    return links


def resolve(root, output, hf_root=None):
    root, output = Path(root), Path(output)
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    if report["status"] != "COMPLETE_STREAM_AUDIT":
        raise ValueError("Finish the complete archive pass before resolving references")
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(root / "members.sqlite")
    hf = defaultdict(list)
    source = None
    native_groups = defaultdict(set)
    rejected_refs = 0
    if hf_root:
        source = sqlite3.connect(Path(hf_root) / "observations.sqlite")
        for signature, identity, file, line in source.execute(
            "SELECT near,id,file,line FROM observations WHERE file LIKE 'filtered/%'"
        ):
            hf[signature].append({"observation_id": identity, "file": file, "line": line})
    totals, outcomes, roles, groups = Counter(), Counter(), Counter(), Counter()
    dest = output / "native-filtered-reference-ledger.jsonl.gz"
    with gzip.open(dest, "wt", encoding="utf-8", compresslevel=6) as stream:
        for member, payload in db.execute("SELECT * FROM filtered_refs ORDER BY path"):
            raw_member = member.replace("anonymized/filtered/", "anonymized/data/", 1)
            found = db.execute(
                "SELECT payload FROM event_indexes WHERE path=?", (raw_member,)
            ).fetchone()
            events = (
                [json.loads(line) for line in zlib.decompress(found[0]).splitlines()]
                if found
                else []
            )
            member_hash = db.execute(
                "SELECT sha FROM members WHERE path=?", (raw_member,)
            ).fetchone()
            for line in zlib.decompress(payload).splitlines():
                record = json.loads(line)
                links = link_record(record, events)
                candidates = []
                for candidate in hf.get(record["core_signature"], []):
                    from training.fireball_observations import dumps, unpacked

                    original = unpacked(
                        source.execute(
                            "SELECT payload FROM observations WHERE id=?",
                            (candidate["observation_id"],),
                        ).fetchone()[0]
                    )
                    refs = {k: v for k, v in original.items() if k.endswith(("_idx", "_idxs"))}
                    if dumps(refs) != dumps(record["refs"]):
                        rejected_refs += 1
                        continue
                    candidates.append(candidate)
                    native_groups[candidate["observation_id"]].add(member)
                value = {
                    "schema": "fireball-native-reference-observation-v1",
                    "member": member,
                    "line": record["line"],
                    "line_sha256": record["line_sha256"],
                    "raw_member": raw_member,
                    "raw_member_sha256": member_hash[0] if member_hash else None,
                    "archive_sha256": report["archive_sha256"],
                    "links": links,
                    "hf_content_correspondence_candidates": candidates,
                    "hf_correspondence_status": (
                        "NORMALIZED_CORE_AND_EXACT_REFERENCE_VECTOR_NOT_BYTE_IDENTITY"
                    ),
                    "dm_role": "UNKNOWN_NOT_INFERRED_FROM_AUTHOR_BOT_FALSE",
                    "human_approved": False,
                    "train_admitted": False,
                }
                # Cap derivative storage independently of the archive size.
                if dest.exists() and dest.stat().st_size > 128 * 1024**2:
                    raise OSError("LINK_LEDGER_BUDGET_REACHED; retain the existing source index")
                import shutil

                if shutil.disk_usage(output).free < 192 * 1024**2:
                    raise OSError("LINK_LEDGER_FREE_SPACE_RESERVE_REACHED")
                stream.write(json.dumps(value, ensure_ascii=True) + "\n")
                totals["native_filtered_records"] += 1
                totals["hf_content_candidate_records"] += bool(candidates)
                for link in links:
                    outcomes[link["status"]] += 1
                    if (
                        link["field"] == "after_idxs"
                        and link["status"] == "INDEX_AND_TYPE_CONFIRMED"
                    ):
                        roles[link["role"]] += 1
            groups["paired_raw_member" if found else "missing_raw_member"] += 1
            if sum(groups.values()) % 100 == 0:
                print(
                    json.dumps(
                        {
                            "linked_native_filtered_files": sum(groups.values()),
                            "records": dict(totals),
                        }
                    ),
                    flush=True,
                )
    db.close()
    if source:
        source.close()
    group_path = output / "hf-native-group-map.jsonl.gz"
    with gzip.open(group_path, "wt", encoding="utf-8") as group_file:
        for identity, values in sorted(native_groups.items()):
            if len(values) == 1:
                group_file.write(
                    json.dumps({"hf_observation_id": identity, "native_group": next(iter(values))})
                    + "\n"
                )
    result = {
        "schema": "fireball-complete-native-reference-resolution-v1",
        "status": "COMPLETE",
        "archive_sha256": report["archive_sha256"],
        "counts": dict(totals),
        "groups": dict(groups),
        "link_statuses": dict(outcomes),
        "after_reference_roles": dict(roles),
        "hf_mapping": (
            "core+reference correspondences; existing HF roles/splits/admission unchanged"
        ),
        "canonical_raw_storage": "SEE_SOURCE_REPORT_NOT_CLAIMED_BY_INDEX",
        "human_approved": 0,
        "train_admitted": 0,
        "training_steps": 0,
        "ledger_sha256": file_sha(dest),
        "ledger_bytes": dest.stat().st_size,
        "rejected_reference_vector_candidates": rejected_refs,
        "unique_native_group_mappings": sum(len(v) == 1 for v in native_groups.values()),
        "ambiguous_native_group_mappings": sum(len(v) > 1 for v in native_groups.values()),
        "native_group_map_sha256": file_sha(group_path),
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--hf-root", type=Path)
    a = p.parse_args()
    print(json.dumps(resolve(a.root, a.output, a.hf_root), indent=2))


if __name__ == "__main__":
    main()
