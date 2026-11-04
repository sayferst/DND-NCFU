"""Bounded-memory, resumable archival of an entire pinned FIREBALL filtered tree."""

import argparse
import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen


def connect(root):
    db = sqlite3.connect(Path(root) / "downloads.sqlite", timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,bytes INT"
        "EGER,sha256 TEXT,status TEXT,error TEXT)"
    )
    return db


def file_digests(path):
    size = path.stat().st_size
    sha = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
            blob.update(chunk)
    return size, sha.hexdigest(), blob.hexdigest()


def download(root, entry, revision):
    root = Path(root)
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe archive path")
    dest = root / "originals" / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    db = connect(root)
    saved = db.execute(
        "SELECT bytes,sha256,status FROM files WHERE path=?", (entry["path"],)
    ).fetchone()
    if dest.exists() and saved and saved[2] == "OK":
        size, h, blob = file_digests(dest)
        pinned = h == entry["lfs"].get("oid") if entry.get("lfs") else blob == entry.get("oid")
        if size == saved[0] == entry["size"] and h == saved[1] and pinned:
            db.close()
            return "CACHED"
        db.close()
        raise ValueError("Immutable downloaded source changed: " + entry["path"])
    partial = dest.with_suffix(dest.suffix + ".partial")
    error = None
    for attempt in range(4):
        try:
            start = partial.stat().st_size if partial.exists() else 0
            url = f"https://huggingface.co/datasets/lara-martin/FIREBALL/resolve/{revision}/"
            url += entry["path"]
            req = Request(url, headers={"Range": f"bytes={start}-"} if start else {})
            with urlopen(req, timeout=45) as response:
                append = start > 0 and response.status == 206
                if append and not response.headers.get("Content-Range", "").startswith(
                    f"bytes {start}-"
                ):
                    raise ValueError("Wrong resume offset")
                with partial.open("ab" if append else "wb") as out:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
                        if out.tell() > entry["size"]:
                            raise ValueError("Source larger than pinned size")
            size, sha, blob = file_digests(partial)
            if size != entry["size"]:
                raise ValueError("Incomplete download")
            if entry.get("lfs"):
                expected = entry["lfs"].get("oid")
                if expected and sha != expected:
                    raise ValueError("LFS digest mismatch")
            elif entry.get("oid"):
                if blob != entry["oid"]:
                    raise ValueError("Pinned Git blob mismatch")
            if dest.exists():
                raise ValueError("Refusing to replace original")
            os.rename(partial, dest)
            db.execute(
                "INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)",
                (entry["path"], size, sha, "OK", None),
            )
            db.commit()
            db.close()
            return "OK"
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
            if partial.exists() and partial.stat().st_size == entry["size"]:
                # Keep corrupt complete bytes for inspection, restart under a new partial.
                partial.rename(partial.with_name(partial.name + f".bad-{time.time_ns()}"))
            time.sleep(min(2**attempt, 8))
    db.execute(
        "INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)",
        (entry["path"], entry["size"], None, "FAILED", error),
    )
    db.commit()
    db.close()
    return "FAILED"


def fetch(root, workers=6):
    root = Path(root)
    manifest = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    entries = [
        e
        for e in manifest["entries"]
        if e["path"].startswith("filtered/") and e["path"].endswith(".jsonl")
    ]
    expected = {
        line.strip().removeprefix("filtered/")
        for line in (root / "files.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    actual = {Path(e["path"]).name for e in entries}
    comparison = {
        "tree_files": len(entries),
        "listed_files": len(expected),
        "missing_from_tree": sorted(expected - actual),
        "unlisted_in_tree": sorted(actual - expected),
    }
    (root / "tree-comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    connect(root).close()
    counts = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks = [pool.submit(download, root, e, manifest["revision"]) for e in entries]
        for index, future in enumerate(as_completed(tasks), 1):
            result = future.result()
            counts[result] = counts.get(result, 0) + 1
            if index % 25 == 0 or index == len(tasks):
                print(
                    json.dumps({"processed": index, "total": len(tasks), "counts": counts}),
                    flush=True,
                )
    return comparison | {"results": counts}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    print(json.dumps(fetch(a.root, a.workers), indent=2))


if __name__ == "__main__":
    main()
