"""Bounded read-only inspection. Documents are data, never commands."""

import argparse
import hashlib
import json
import sqlite3
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

LIMIT = 128 * 1024 * 1024


def members(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("Invalid or oversized source")

    def safe(name):
        p = PurePosixPath(name)
        if "\\" in name or ":" in name or "\x00" in name or p.is_absolute() or ".." in p.parts:
            raise ValueError("Unsafe archive path")

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 20000 or sum(i.file_size for i in infos) > LIMIT:
                raise ValueError("Archive limits")
            for i in infos:
                safe(i.orig_filename)
                if i.orig_filename != i.filename or (i.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive link or invalid name")
                if not i.is_dir():
                    yield i.filename, archive.read(i)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            total = 0
            count = 0
            for i in archive:
                safe(i.name)
                total += i.size
                count += 1
                if total > LIMIT or count > 20000 or not (i.isfile() or i.isdir()):
                    raise ValueError("Unsafe tar member")
                if i.isfile():
                    yield i.name, archive.extractfile(i).read(i.size + 1)
    elif path.suffix.lower() == ".7z":
        raise ValueError("7z unavailable: export as ZIP; no extraction backend installed")
    elif path.suffix.lower() in (".sqlite3", ".sqlite", ".db"):
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            # Only a documented table, no views or SQL from the source.
            found = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='gm_samples'"
            ).fetchone()
            if not found:
                raise ValueError("SQLite requires gm_samples(payload TEXT)")
            total = 0
            for n, (text,) in enumerate(db.execute("SELECT payload FROM gm_samples LIMIT 20001")):
                raw = text.encode("utf-8")
                total += len(raw)
                if n >= 20000 or total > LIMIT:
                    raise ValueError("SQLite limits")
                yield f"row{n}.json", raw
    else:
        yield path.name, path.read_bytes()


def inspect(path):
    files = []
    samples = []
    for name, raw in members(path):
        files.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        if Path(name).suffix.lower() not in (".json", ".jsonl", ".md", ".txt"):
            continue
        text = raw.decode("utf-8-sig", errors="strict")
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                if len(line) > 1000000:
                    raise ValueError("Oversized record")
                if line.strip():
                    samples.append(json.loads(line))
        elif name.endswith(".json"):
            value = json.loads(text)
            if isinstance(value, list):
                samples.extend(value)
            elif isinstance(value, dict) and value.get("schema_version") == "gm-sft-v1":
                samples.append(value)
    return {
        "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "files": files,
        "file_count": len(files),
        "candidate_samples": len(samples),
        "campaigns": len({str(s.get("campaign_id")) for s in samples if isinstance(s, dict)}),
        "real_receipts": sum(
            isinstance(s, dict) and isinstance(s.get("engine_receipt"), dict) for s in samples
        ),
    }, samples


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    a = p.parse_args()
    report, _ = inspect(a.input)
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
