"""Stream the entire official raw tar/gzip release, optionally preserve canonical observations.

Audit mode stores exhaustive member accounting and hash chains, NOT full canonical data.
Canonical mode writes every source JSON value in a separate compressed local envelope.
No archive paths are extracted, source commands executed, or training approvals inferred.
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import uuid
import zlib
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

from training.fireball_discover import RAW_URL
from training.fireball_observations import dumps, source_role, strict_source_json


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.sha = hashlib.sha256()
        self.bytes = 0

    def read(self, size=-1):
        if size < 0:
            raise ValueError("Unbounded source read forbidden")
        data = self.stream.read(size)
        self.sha.update(data)
        self.bytes += len(data)
        return data


def inspect_stream(
    stream,
    output,
    binding,
    *,
    canonical=False,
    link_index=False,
    max_output_mib=256,
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    job = output / "source-binding.json"
    binding = binding | {
        "canonical_requested": canonical,
        "link_index": link_index,
        "max_output_mib": max_output_mib,
    }
    limit = max_output_mib * 1024**2
    reserve = 192 * 1024**2
    stored_bytes = sum(
        p.stat().st_size
        for folder in ("canonical", "filtered-members")
        for p in (output / folder).glob("*")
        if p.is_file()
    )

    def guard(extra=0, temporary=None):
        db_bytes = sum(p.stat().st_size for p in output.glob("members.sqlite*") if p.is_file())
        pending = temporary.stat().st_size if temporary and temporary.exists() else 0
        if db_bytes + stored_bytes + pending + extra + 32768 > limit:
            raise OSError("OUTPUT_BUDGET_REACHED: source remains external; increase local budget")
        if shutil.disk_usage(output).free - extra < reserve:
            raise OSError("FREE_SPACE_RESERVE_REACHED: no more source data will be written")

    guard()
    if job.exists() and json.loads(job.read_text(encoding="utf-8")) != binding:
        raise ValueError("Changed source binding or storage mode; choose a new directory")
    job.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    db = sqlite3.connect(output / "members.sqlite", timeout=60)
    db.execute(
        "CREATE TABLE IF NOT EXISTS members(path TEXT PRIMARY KEY,bytes INTEGER,sha TEXT,"
        "stats TEXT,canonical_path TEXT,canonical_sha TEXT)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS event_indexes(path TEXT PRIMARY KEY,payload BLOB)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS filtered_sources(path TEXT PRIMARY KEY,"
        "local_path TEXT,sha256 TEXT)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS filtered_refs(path TEXT PRIMARY KEY,payload BLOB)")
    db.commit()
    outer = HashReader(stream)
    seen = set()
    resumed = 0
    total = 0
    (output / "RUNNING.json").write_text('{"status":"RUNNING_NOT_COMPLETE"}\n', encoding="utf-8")
    try:
        with gzip.GzipFile(fileobj=outer) as uncompressed:
            with tarfile.open(fileobj=uncompressed, mode="r|") as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    if member.name in seen:
                        raise ValueError("Duplicate archive member: " + member.name)
                    guard()
                    seen.add(member.name)
                    total += 1
                    saved = db.execute(
                        "SELECT bytes,sha,canonical_path,canonical_sha FROM members WHERE path=?",
                        (member.name,),
                    ).fetchone()
                    hashed = HashReader(tar.extractfile(member))
                    if saved:
                        while hashed.read(1024 * 1024):
                            pass
                        if saved[:2] != (hashed.bytes, hashed.sha.hexdigest()):
                            raise ValueError("Previously scanned source member changed")
                        if canonical and saved[2] and not (output / saved[2]).is_file():
                            pending = Path(str(output / saved[2]) + ".partial")
                            if pending.is_file() and file_sha(pending) == saved[3]:
                                os.rename(pending, output / saved[2])
                        if canonical and (not saved[2] or not (output / saved[2]).is_file()):
                            raise ValueError("Missing previously saved canonical member")
                        if canonical and file_sha(output / saved[2]) != saved[3]:
                            raise ValueError("Previously saved canonical member changed")
                        resumed += 1
                        continue
                    stats = {
                        "lines": 0,
                        "parsed": 0,
                        "quarantine": 0,
                        "event_types": Counter(),
                        "roles": Counter(),
                        "top_level_fields": Counter(),
                        "parse_errors": Counter(),
                    }
                    chain = hashlib.sha256()
                    index_zip = zlib.compressobj(3) if link_index else None
                    index_parts = []
                    refs_zip = (
                        zlib.compressobj(3)
                        if link_index and member.name.startswith("anonymized/filtered/")
                        else None
                    )
                    refs_parts = []
                    dest = None
                    relative = None
                    if canonical:
                        relative = (
                            "canonical/"
                            + hashlib.sha256(member.name.encode()).hexdigest()
                            + ".jsonl.gz"
                        )
                        dest = output / relative
                        dest.parent.mkdir(exist_ok=True)
                        if dest.exists():
                            raise ValueError(
                                "Unaccounted canonical output exists; inspect before resuming"
                            )
                    if dest and Path(str(dest) + ".partial").exists():
                        pending = Path(str(dest) + ".partial")
                        pending.rename(str(pending) + ".interrupted-" + uuid.uuid4().hex)
                    writer = (
                        gzip.open(str(dest) + ".partial", "xt", encoding="utf-8") if dest else None
                    )
                    try:
                        if member.name.endswith(".jsonl.gz"):
                            with gzip.GzipFile(fileobj=hashed) as records:
                                for number, line in enumerate(records, 1):
                                    sha = hashlib.sha256(line).hexdigest()
                                    chain.update(bytes.fromhex(sha))
                                    stats["lines"] += 1
                                    try:
                                        value = strict_source_json(line)
                                        kind = (
                                            str(value.get("event_type", "filtered_turn"))
                                            if isinstance(value, dict)
                                            else "json_value"
                                        )
                                        role, evidence = (
                                            source_role(value)
                                            if isinstance(value, dict)
                                            else ("unknown", "not_object")
                                        )
                                        stats["parsed"] += 1
                                        stats["event_types"][kind] += 1
                                        stats["roles"][role] += 1
                                        if isinstance(value, dict):
                                            stats["top_level_fields"].update(value.keys())
                                        record = {
                                            "original": value,
                                            "status": "PRESERVED",
                                            "role": role,
                                            "role_evidence": evidence,
                                        }
                                    except (ValueError, UnicodeError, RecursionError) as error:
                                        import base64

                                        stats["quarantine"] += 1
                                        stats["parse_errors"][type(error).__name__] += 1
                                        record = {
                                            "raw_line_base64": base64.b64encode(line).decode(),
                                            "status": "QUARANTINE",
                                            "reason": str(error),
                                        }
                                    if refs_zip and record["status"] == "PRESERVED":
                                        from training.fireball_audit import core_signature

                                        refs_parts.append(
                                            refs_zip.compress(
                                                dumps(
                                                    {
                                                        "line": number,
                                                        "line_sha256": sha,
                                                        "core_signature": core_signature(value),
                                                        "refs": {
                                                            k: v
                                                            for k, v in value.items()
                                                            if k.endswith(("_idx", "_idxs"))
                                                        },
                                                    }
                                                ).encode()
                                                + b"\n"
                                            )
                                        )
                                    if index_zip:
                                        event_type = (
                                            str(value.get("event_type", "filtered_turn"))
                                            if record["status"] == "PRESERVED"
                                            and isinstance(value, dict)
                                            else record["status"]
                                        )
                                        index_parts.append(
                                            index_zip.compress(
                                                dumps(
                                                    [
                                                        event_type,
                                                        record.get("role", "unknown"),
                                                        record.get(
                                                            "role_evidence", "parse_quarantine"
                                                        ),
                                                        value.get("author_id")
                                                        if record["status"] == "PRESERVED"
                                                        and isinstance(value, dict)
                                                        else None,
                                                    ]
                                                ).encode()
                                                + b"\n"
                                            )
                                        )
                                    if writer:
                                        record.update(
                                            schema="fireball-native-raw-observation-v1",
                                            source_member=member.name,
                                            source_line=number,
                                            line_sha256=sha,
                                            source_binding=binding,
                                            human_approved=False,
                                            train_admitted=False,
                                            runtime="EXTERNAL_NOT_ASSESSED",
                                        )
                                        text = dumps(record) + "\n"
                                        guard(len(text.encode()), Path(str(dest) + ".partial"))
                                        writer.write(text)
                        else:
                            while hashed.read(1024 * 1024):
                                pass
                        # Consume any trailing source bytes as part of the immutable member digest.
                        while hashed.read(1024 * 1024):
                            pass
                    finally:
                        if writer:
                            writer.close()
                    if hashed.bytes != member.size:
                        raise ValueError("Incomplete source member")
                    pending_canonical = Path(str(dest) + ".partial") if dest else None
                    if dest:
                        stored_bytes += pending_canonical.stat().st_size
                    stats["ordered_line_sha256_chain"] = chain.hexdigest()
                    if refs_zip:
                        refs_parts.append(refs_zip.flush())
                        refs_payload = b"".join(refs_parts)
                        guard(len(refs_payload) * 2 + 32768)
                        db.execute(
                            "INSERT INTO filtered_refs VALUES(?,?)", (member.name, refs_payload)
                        )
                    if index_zip:
                        index_parts.append(index_zip.flush())
                        guard(sum(map(len, index_parts)) * 2 + len(dumps(stats)) * 3 + 32768)
                        db.execute(
                            "INSERT INTO event_indexes VALUES(?,?)",
                            (member.name, b"".join(index_parts)),
                        )
                    db.execute(
                        "INSERT INTO members VALUES(?,?,?,?,?,?)",
                        (
                            member.name,
                            hashed.bytes,
                            hashed.sha.hexdigest(),
                            dumps(stats),
                            relative,
                            file_sha(pending_canonical) if dest else None,
                        ),
                    )
                    db.commit()
                    if dest:
                        os.rename(pending_canonical, dest)
                    if total % 100 == 0 or total <= 3:
                        print(
                            dumps(
                                {
                                    "members": total,
                                    "last_member": member.name,
                                    "member_lines": stats["lines"],
                                    "archive_bytes_read": outer.bytes,
                                }
                            ),
                            flush=True,
                        )
            # Complete gzip trailer/CRC and archive hash, even beyond tar end padding.
            while uncompressed.read(1024 * 1024):
                pass
        while outer.read(1024 * 1024):
            pass
        if binding.get("bytes") is not None and outer.bytes != binding["bytes"]:
            raise ValueError("Archive byte count differs from pinned source length")
    except (OSError, EOFError, ValueError, tarfile.TarError) as error:
        failure = {
            "status": "FAILED_SOURCE_INTEGRITY_NOT_COMPLETE",
            "error": type(error).__name__,
            "message": str(error),
            "archive_bytes_read": outer.bytes,
            "expected_archive_bytes": binding.get("bytes"),
            "consumed_bytes_sha256": outer.sha.hexdigest(),
            "http_unread_length": getattr(stream, "length", None),
            "completed_members": db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
            "canonical_storage": "NOT_CLAIMED_COMPLETE",
        }
        run = uuid.uuid4().hex
        (output / ("failure-" + run + ".json")).write_text(
            json.dumps(failure, indent=2) + "\n", encoding="utf-8"
        )
        (output / "RUNNING.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        db.close()
        raise
    previous_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    if previous_count != len(seen):
        raise ValueError("Source member set changed")
    counts = Counter()
    kinds, roles, fields, errors = Counter(), Counter(), Counter(), Counter()
    for _path, _size, _sha, text, _canonical, _canonical_sha in db.execute("SELECT * FROM members"):
        stat = json.loads(text)
        for key in ("lines", "parsed", "quarantine"):
            counts[key] += stat[key]
        kinds.update(stat["event_types"])
        roles.update(stat["roles"])
        fields.update(stat["top_level_fields"])
        errors.update(stat["parse_errors"])
    result = {
        "schema": "fireball-entire-raw-stream-audit-v1",
        "status": "COMPLETE_STREAM_AUDIT",
        "archive_sha256": outer.sha.hexdigest(),
        "archive_bytes": outer.bytes,
        "source_binding": binding,
        "output_budget_mib": max_output_mib,
        "free_space_reserve_mib": 192,
        "members": total,
        "resumed_members": resumed,
        "records": dict(counts),
        "event_types": dict(kinds),
        "source_roles": dict(roles),
        "top_level_fields": dict(fields),
        "parse_errors": dict(errors),
        "canonical_storage": "COMPLETE" if canonical else "NOT_MATERIALIZED_AUDIT_ONLY",
        "original_archive_storage": (
            "EXTERNAL_SOURCE_OR_OWNER_LOCAL_ARCHIVE_NOT_COPIED_BY_THIS_COMMAND"
        ),
        "per_record_proof": (
            "ordered SHA256(line) chains per member; "
            "not a per-record canonical ledger in audit mode"
        ),
        "human_approved": 0,
        "train_admitted": 0,
        "training_steps": 0,
    }
    db.close()
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "RUNNING.json").write_text('{"status":"COMPLETED_SEE_REPORT"}\n', encoding="utf-8")
    return result


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while data := stream.read(1024 * 1024):
            h.update(data)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--official-url", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--canonical", action="store_true")
    p.add_argument("--link-index", action="store_true")
    p.add_argument("--max-output-mib", type=int, default=256)
    a = p.parse_args()
    if a.archive:
        with a.archive.open("rb") as stream:
            result = inspect_stream(
                stream,
                a.output,
                {"local_archive": str(a.archive.resolve()), "bytes": a.archive.stat().st_size},
                canonical=a.canonical,
                link_index=a.link_index,
                max_output_mib=a.max_output_mib,
            )
    else:
        with urlopen(
            Request(RAW_URL, headers={"User-Agent": "DND-NCFU-research-archive"}), timeout=90
        ) as stream:
            if stream.status != 200:
                raise ValueError("Expected complete source HTTP200")
            binding = {
                "url": RAW_URL,
                "etag": stream.headers.get("ETag"),
                "last_modified": stream.headers.get("Last-Modified"),
                "bytes": int(stream.headers["Content-Length"]),
            }
            result = inspect_stream(
                stream,
                a.output,
                binding,
                canonical=a.canonical,
                link_index=a.link_index,
                max_output_mib=a.max_output_mib,
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
