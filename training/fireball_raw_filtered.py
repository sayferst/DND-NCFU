"""Bounded mirror of ALL native filtered members from the verified raw archive.

Raw data bodies are streamed, hash-checked and not stored. Native filtered blobs retain every byte.
"""

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen

from training.fireball_raw import HashReader


def mirror(stream, audit_root, output, *, max_output_mib=160):
    audit_root, output = Path(audit_root), Path(output)
    report = json.loads((audit_root / "report.json").read_text(encoding="utf-8"))
    if report["status"] != "COMPLETE_STREAM_AUDIT":
        raise ValueError("Verified complete source audit required")
    source = sqlite3.connect(audit_root / "members.sqlite")
    expected = {p: (n, sha) for p, n, sha in source.execute("SELECT path,bytes,sha FROM members")}
    source.close()
    filtered_bytes = sum(
        n for p, (n, _) in expected.items() if p.startswith("anonymized/filtered/")
    )
    if filtered_bytes * 1.5 + 8 * 1024**2 > max_output_mib * 1024**2:
        raise OSError("Filtered source exceeds bounded output budget")
    output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output).free < 192 * 1024**2 + filtered_bytes * 1.5:
        raise OSError("Insufficient free space including reserve")
    db = sqlite3.connect(output / "filtered.sqlite")
    db.execute(
        "CREATE TABLE IF NOT EXISTS filtered(path TEXT PRIMARY KEY,sha256 TEXT,payload BLOB)"
    )
    raw = HashReader(stream)
    seen = set()
    saved = 0
    with gzip.GzipFile(fileobj=raw) as gz:
        with tarfile.open(fileobj=gz, mode="r|") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                if member.name in seen or member.name not in expected:
                    raise ValueError("Unexpected source member")
                seen.add(member.name)
                hashed = HashReader(tar.extractfile(member))
                chunks = []
                retain = member.name.startswith("anonymized/filtered/")
                while chunk := hashed.read(1024 * 1024):
                    if retain:
                        chunks.append(chunk)
                if (hashed.bytes, hashed.sha.hexdigest()) != expected[member.name]:
                    raise ValueError("Source member changed")
                if retain:
                    if (
                        output / "filtered.sqlite"
                    ).stat().st_size + member.size * 2 + 32768 > max_output_mib * 1024**2:
                        raise OSError("Output budget reached")
                    if shutil.disk_usage(output).free < 192 * 1024**2 + member.size * 2:
                        raise OSError("Free space reserve reached")
                    blob = b"".join(chunks)
                    old = db.execute(
                        "SELECT sha256,payload FROM filtered WHERE path=?", (member.name,)
                    ).fetchone()
                    if old and (
                        old[0] != hashed.sha.hexdigest()
                        or hashlib.sha256(old[1]).hexdigest() != old[0]
                    ):
                        raise ValueError("Immutable filtered source changed")
                    if not old:
                        db.execute(
                            "INSERT INTO filtered VALUES(?,?,?)",
                            (member.name, hashed.sha.hexdigest(), blob),
                        )
                        db.commit()
                    saved += 1
                if len(seen) % 2000 == 0:
                    print(
                        json.dumps({"verified_members": len(seen), "filtered_saved": saved}),
                        flush=True,
                    )
        while gz.read(1024 * 1024):
            pass
    while raw.read(1024 * 1024):
        pass
    if (
        seen != set(expected)
        or raw.sha.hexdigest() != report["archive_sha256"]
        or raw.bytes != report["archive_bytes"]
    ):
        raise ValueError("Archive identity mismatch; no complete mirror report")
    count = db.execute("SELECT COUNT(*) FROM filtered").fetchone()[0]
    db.close()
    if count != saved:
        raise ValueError("Unexpected retained filtered member set")
    result = {
        "schema": "fireball-native-filtered-mirror-v1",
        "status": "COMPLETE",
        "archive_sha256": raw.sha.hexdigest(),
        "archive_bytes": raw.bytes,
        "verified_members": len(seen),
        "native_filtered_files": saved,
        "compressed_source_bytes": filtered_bytes,
        "raw_body_storage": "NOT_COPIED",
        "filtered_body_storage": "ALL_ORIGINAL_COMPRESSED_MEMBER_BYTES",
        "max_output_mib": max_output_mib,
        "human_approved": 0,
        "train_admitted": 0,
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = json.loads((a.audit_root / "report.json").read_text(encoding="utf-8"))
    with urlopen(
        Request(
            report["source_binding"]["url"], headers={"If-Match": report["source_binding"]["etag"]}
        ),
        timeout=90,
    ) as src:
        if src.status != 200 or src.headers.get("ETag") != report["source_binding"]["etag"]:
            raise ValueError("Source version/status changed; do not mirror")
        print(json.dumps(mirror(src, a.audit_root, a.output), indent=2))


if __name__ == "__main__":
    main()
