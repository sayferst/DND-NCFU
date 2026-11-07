"""Recover time-local DM accounts and referenced messages from the pinned raw archive.

Only source messages referenced by filtered triples are retained. This is a
derivative role/text index, not a replacement for the canonical raw archive.
The old index and all previously delivered corpora are read-only.
"""

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import tarfile
import uuid
import zlib
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

from training.fireball_discover import RAW_URL
from training.fireball_observations import dumps, strict_source_json
from training.fireball_raw import HashReader, file_sha


def account_id(value):
    return str(value) if type(value) in (str, int) and str(value).strip() else None


def extract_member(records, wanted):
    messages, changes, counts = [], [], Counter()
    current = None
    last_dm = object()
    for index, line in enumerate(records):
        counts["lines"] += 1
        line_sha = hashlib.sha256(line).hexdigest()
        try:
            event = strict_source_json(line)
            if not isinstance(event, dict):
                raise ValueError("source event is not an object")
        except (ValueError, UnicodeError, RecursionError):
            counts["quarantine"] += 1
            # An unreadable event might have changed the DM; never carry stale authority.
            current = None
            if index in wanted:
                messages.append({"index": index, "status": "QUARANTINE", "line_sha256": line_sha})
            continue
        kind = event.get("event_type")
        if kind == "combat_state_update":
            counts["state_updates"] += 1
            data = event.get("data")
            dm = account_id(data.get("dm")) if isinstance(data, dict) else None
            current = {"dm_id": dm, "state_index": index, "state_line_sha256": line_sha}
            if dm != last_dm:
                changes.append(current.copy())
                last_dm = dm
        if index not in wanted:
            continue
        if kind != "message":
            messages.append({"index": index, "status": "NOT_MESSAGE", "event_type": kind})
            continue
        author = account_id(event.get("author_id"))
        bot = event.get("author_bot")
        role = "unknown"
        if bot is True:
            role = "bot"
        elif author is not None and current and current["dm_id"] is not None:
            role = "dungeon_master_account" if author == current["dm_id"] else "non_dm_account"
        counts[role] += 1
        messages.append(
            {
                "index": index,
                "status": "SOURCE_MESSAGE",
                "author_id": author,
                "author_bot": bot,
                "role": role,
                "role_evidence": current.copy() if current else None,
                "content": event.get("content"),
                "line_sha256": line_sha,
            }
        )
    counts["requested_indices"] = len(wanted)
    counts["retrieved_indices"] = len(messages)
    counts["missing_indices"] = len(wanted - {m["index"] for m in messages})
    return messages, changes, dict(counts)


def scan(stream, index_root, output, *, max_output_mib=128):
    index_root, output = Path(index_root), Path(output)
    source = json.loads((index_root / "report.json").read_text(encoding="utf-8"))
    if source.get("status") != "COMPLETE_STREAM_AUDIT":
        raise ValueError("A verified complete raw index is required")
    output.mkdir(parents=True, exist_ok=True)
    binding = {
        "schema": "fireball-time-local-dm-index-v1",
        "archive_sha256": source["archive_sha256"],
        "archive_bytes": source["archive_bytes"],
        "source_index_sha256": file_sha(index_root / "members.sqlite"),
        "max_output_mib": max_output_mib,
    }
    job = output / "source-binding.json"
    if job.exists() and json.loads(job.read_text(encoding="utf-8")) != binding:
        raise ValueError("Changed raw/role job; choose a new output")
    job.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    original = sqlite3.connect(
        (index_root / "members.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    db = sqlite3.connect(output / "roles.sqlite")
    db.execute(
        "CREATE TABLE IF NOT EXISTS members(path TEXT PRIMARY KEY,bytes INTEGER,"
        "sha256 TEXT,messages BLOB,changes BLOB,stats TEXT,payload_sha256 TEXT)"
    )
    db.commit()

    def guard(extra=0):
        size = sum(p.stat().st_size for p in output.glob("roles.sqlite*") if p.is_file())
        if size + extra + 65536 > max_output_mib * 1024**2:
            raise OSError("ROLE_INDEX_OUTPUT_BUDGET_REACHED")
        if shutil.disk_usage(output).free - extra < 192 * 1024**2:
            raise OSError("ROLE_INDEX_FREE_SPACE_RESERVE_REACHED")

    guard()
    outer = HashReader(stream)
    seen, cached = set(), 0
    try:
        with gzip.GzipFile(fileobj=outer) as uncompressed:
            with tarfile.open(fileobj=uncompressed, mode="r|") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    guard()
                    if member.name in seen:
                        raise ValueError("Duplicate source member")
                    seen.add(member.name)
                    expected = original.execute(
                        "SELECT bytes,sha FROM members WHERE path=?", (member.name,)
                    ).fetchone()
                    if not expected:
                        raise ValueError("Member absent from pinned raw index")
                    filtered = member.name.replace("anonymized/data/", "anonymized/filtered/", 1)
                    refs = (
                        original.execute(
                            "SELECT payload FROM filtered_refs WHERE path=?", (filtered,)
                        ).fetchone()
                        if member.name.startswith("anonymized/data/")
                        else None
                    )
                    saved = db.execute(
                        "SELECT bytes,sha256,messages,changes,payload_sha256 "
                        "FROM members WHERE path=?",
                        (member.name,),
                    ).fetchone()
                    hashed = HashReader(archive.extractfile(member))
                    if refs and saved is None:
                        wanted = set()
                        for line in zlib.decompress(refs[0]).splitlines():
                            ref = json.loads(line)["refs"]
                            for key in ("before_idxs", "after_idxs"):
                                values = ref.get(key)
                                if isinstance(values, list):
                                    wanted.update(x for x in values if type(x) is int and x >= 0)
                        with gzip.GzipFile(fileobj=hashed) as records:
                            messages, changes, stats = extract_member(records, wanted)
                        payload = zlib.compress(dumps(messages).encode(), 6)
                        timeline = zlib.compress(dumps(changes).encode(), 6)
                        guard(3 * (len(payload) + len(timeline)))
                    while hashed.read(1024 * 1024):
                        pass
                    if (
                        expected != (hashed.bytes, hashed.sha.hexdigest())
                        or member.size != hashed.bytes
                    ):
                        raise ValueError("Pinned compressed member changed")
                    if refs:
                        if saved is not None:
                            if (
                                saved[:2] != expected
                                or hashlib.sha256(saved[2] + saved[3]).hexdigest() != saved[4]
                            ):
                                raise ValueError("Cached role index changed")
                            cached += 1
                        else:
                            db.execute(
                                "INSERT INTO members VALUES(?,?,?,?,?,?,?)",
                                (
                                    member.name,
                                    hashed.bytes,
                                    hashed.sha.hexdigest(),
                                    payload,
                                    timeline,
                                    dumps(stats),
                                    hashlib.sha256(payload + timeline).hexdigest(),
                                ),
                            )
                            db.commit()
                    if len(seen) % 250 == 0:
                        print(
                            dumps(
                                {
                                    "members": len(seen),
                                    "raw_bytes_read": outer.bytes,
                                    "role_groups": db.execute(
                                        "SELECT COUNT(*) FROM members"
                                    ).fetchone()[0],
                                    "resumed_role_groups": cached,
                                }
                            ),
                            flush=True,
                        )
            while uncompressed.read(1024 * 1024):
                pass
        while outer.read(1024 * 1024):
            pass
        if (
            outer.bytes != source["archive_bytes"]
            or outer.sha.hexdigest() != source["archive_sha256"]
        ):
            raise ValueError("Full pinned archive SHA/size differs")
        expected_groups = original.execute("SELECT COUNT(*) FROM filtered_refs").fetchone()[0]
        actual_groups = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        if actual_groups != expected_groups or len(seen) != source["members"]:
            raise ValueError("Incomplete role source coverage")
        counts = Counter()
        for (text,) in db.execute("SELECT stats FROM members"):
            counts.update(json.loads(text))
        report = binding | {
            "status": "COMPLETE_REFERENCED_MESSAGE_ROLE_INDEX",
            "all_archive_members_hash_verified": len(seen),
            "native_filtered_groups": actual_groups,
            "resumed_role_groups": cached,
            "counts": dict(counts),
            "role_scope": (
                "ACCOUNT_MATCHES_EXPLICIT_DM_IN_PRECEDING_STATE_NOT_PROOF_OF_TEXT_AUTHORSHIP"
            ),
            "raw_storage": "ONLY_REFERENCED_MESSAGES_AND_DM_TIMELINES_NOT_FULL_CANONICAL_RAW",
            "human_approved": 0,
            "train_admitted": 0,
            "training_steps": 0,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    except (OSError, EOFError, ValueError, tarfile.TarError) as error:
        (output / ("failure-" + uuid.uuid4().hex + ".json")).write_text(
            json.dumps(
                {
                    "status": "FAILED_NOT_COMPLETE",
                    "error": str(error),
                    "bytes_read": outer.bytes,
                    "role_groups": db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        db.close()
        original.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--archive", type=Path)
    inputs.add_argument("--official-url", action="store_true")
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-output-mib", type=int, default=128)
    args = parser.parse_args()
    if args.archive:
        with args.archive.open("rb") as stream:
            report = scan(stream, args.index_root, args.output, max_output_mib=args.max_output_mib)
    else:
        with urlopen(
            Request(RAW_URL, headers={"User-Agent": "DND-NCFU-research/1.0"}), timeout=60
        ) as stream:
            source = json.loads((args.index_root / "report.json").read_text(encoding="utf-8"))
            if int(stream.headers.get("Content-Length", "0")) != source["archive_bytes"]:
                raise ValueError("Remote archive length changed before processing")
            report = scan(stream, args.index_root, args.output, max_output_mib=args.max_output_mib)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
