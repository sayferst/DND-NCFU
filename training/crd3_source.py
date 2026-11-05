"""Pinned CRD3 human transcripts: lossless compressed sources, never execute dataset code."""

import argparse
import gzip
import hashlib
import json
import os
import shutil
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

REVISION = "7fd4515eea411f0f9c5d0a03a8b6b8b2da464e81"
REPOSITORY = "RevanthRameshkumar/CRD3"
LICENSE = "CC-BY-SA-4.0"


def source_entries(tree):
    if tree.get("truncated") or tree.get("sha") != REVISION:
        raise ValueError("Incomplete or unpinned CRD3 tree")
    metadata = {"README.md", "LICENSE"} | {
        "data/aligned data/" + split + "_files" for split in ("train", "val", "test")
    }
    entries = [
        e
        for e in tree["tree"]
        if e["type"] == "blob"
        and (
            e["path"] in metadata
            or e["path"].startswith("data/cleaned data/")
            and e["path"].endswith(".json")
        )
    ]
    if not metadata.issubset({e["path"] for e in entries}):
        raise ValueError("Missing source/license/split metadata")
    return sorted(entries, key=lambda e: e["path"])


def validate_bytes(raw, entry):
    if (
        len(raw) != entry["size"]
        or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != entry["sha"]
    ):
        raise ValueError("CRD3 source differs from the pinned Git blob: " + entry["path"])


def fetch(tree_path, output, *, max_output_mib=64):
    tree = json.loads(Path(tree_path).read_text(encoding="utf-8"))
    entries = source_entries(tree)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    binding = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "license": LICENSE,
        "files": [{k: e[k] for k in ("path", "size", "sha")} for e in entries],
    }
    job = output / "job.json"
    if job.exists() and json.loads(job.read_text(encoding="utf-8")) != binding:
        raise ValueError("Changed CRD3 snapshot; choose a new output")
    job.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    rows = []
    for i, entry in enumerate(entries, 1):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe CRD3 source path")
        path = output / "originals" / (entry["path"] + ".gz")
        if path.exists():
            compressed = path.read_bytes()
            raw = gzip.decompress(compressed)
            validate_bytes(raw, entry)
            cached = True
        else:
            if shutil.disk_usage(output).free - 3 * entry["size"] < 192 * 1024**2:
                raise OSError("CRD3_FREE_SPACE_RESERVE_REACHED")
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/" + quote(
                entry["path"], safe="/"
            )
            with urlopen(
                Request(url, headers={"User-Agent": "DND-NCFU-research/1.0"}), timeout=45
            ) as response:
                raw = response.read(entry["size"] + 1)
            validate_bytes(raw, entry)
            compressed = gzip.compress(raw, mtime=0)
            size = sum(p.stat().st_size for p in (output / "originals").rglob("*") if p.is_file())
            if size + len(compressed) > max_output_mib * 1024**2:
                raise OSError("CRD3_OUTPUT_BUDGET_REACHED")
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_suffix(path.suffix + ".partial")
            with pending.open("wb") as stream:
                stream.write(compressed)
            os.rename(pending, path)
            cached = False
        rows.append(
            {
                "path": entry["path"],
                "bytes": len(raw),
                "git_blob": entry["sha"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "storage": path.relative_to(output).as_posix(),
                "compressed_bytes": len(compressed),
                "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            }
        )
        if i % 10 == 0 or i == len(entries):
            print(json.dumps({"crd3_files_verified": i, "cached": cached}), flush=True)
    report = {
        "schema": "crd3-pinned-sources-v1",
        "status": "ALL_SELECTED_SOURCE_FILES_VERIFIED",
        "repository": REPOSITORY,
        "revision": REVISION,
        "license": LICENSE,
        "selected_scope": "ALL_159_CURRENT_CLEANED_EPISODES_AND_SOURCE_LICENSE_SPLITS",
        "source_storage": "GZIP_OF_EXACT_ORIGINAL_BYTES_LOSSLESS_NOT_NORMALIZED",
        "files": rows,
        "human_row_review": 0,
        "training_steps": 0,
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def read_sources(root):
    root = Path(root)
    report = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (
        report.get("status") != "ALL_SELECTED_SOURCE_FILES_VERIFIED"
        or report.get("revision") != REVISION
    ):
        raise ValueError("Pinned complete CRD3 source snapshot required")
    for entry in report["files"]:
        if not entry["path"].startswith("data/cleaned data/"):
            continue
        compressed = (root / entry["storage"]).read_bytes()
        if hashlib.sha256(compressed).hexdigest() != entry["compressed_sha256"]:
            raise ValueError("Compressed CRD3 source changed")
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Original CRD3 source changed")
        yield entry, json.loads(raw)


class Episodes:
    """Resolve compact pool references against hash-verified immutable episode bytes."""

    def __init__(self, root):
        self.root = Path(root)
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if (
            manifest.get("revision") != REVISION
            or manifest.get("status") != "ALL_SELECTED_SOURCE_FILES_VERIFIED"
        ):
            raise ValueError("Verified CRD3 source snapshot required")
        self.entries = {e["path"]: e for e in manifest["files"]}
        self.cache = OrderedDict()

    def load(self, path):
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        entry = self.entries[path]
        compressed = (self.root / entry["storage"]).read_bytes()
        if hashlib.sha256(compressed).hexdigest() != entry["compressed_sha256"]:
            raise ValueError("CRD3 archive bytes changed")
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("CRD3 original bytes changed")
        value = json.loads(raw)
        self.cache[path] = value
        if len(self.cache) > 4:
            self.cache.popitem(last=False)
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-output-mib", type=int, default=64)
    args = parser.parse_args()
    report = fetch(args.tree, args.output, max_output_mib=args.max_output_mib)
    print(json.dumps({k: report[k] for k in ("status", "revision", "training_steps")}))


if __name__ == "__main__":
    main()
