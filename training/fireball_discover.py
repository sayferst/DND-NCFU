"""Reproduce pinned public inventories and upstream evidence without executing dataset code."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

HF_REVISION = "1b363686ed0d681bf8a0eb1e943af75d3716f7c8"
GITHUB_REVISIONS = {
    "FIREBALL": "02a040bdfc9de5c7da271ca7faad56be090669ba",
    "FIREBALL-data-processing": "b3f9b5eca6dbbe1b7504c14dcbc055687bd4c7b4",
}
RAW_URL = "https://datasets.mechanus.zhu.codes/fireball-anonymized-nov-28-2022-kfdjl.tar.gz"


def immutable_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Pinned evidence differs; choose a new root: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(data)


def get(url):
    with urlopen(
        Request(url, headers={"User-Agent": "DND-NCFU-research-archive"}), timeout=60
    ) as r:
        return r.read(), r.headers


def discover(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    url = f"https://huggingface.co/api/datasets/lara-martin/FIREBALL/tree/{HF_REVISION}?recursive=true&limit=1000"
    pages = 0
    while url:
        if urlparse(url).hostname != "huggingface.co":
            raise ValueError("Unexpected pagination host")
        data, headers = get(url)
        entries.extend(json.loads(data))
        pages += 1
        link = headers.get("Link", "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = match[1] if match else None
    inventory = {
        "dataset": "lara-martin/FIREBALL",
        "revision": HF_REVISION,
        "pages": pages,
        "entries": entries,
    }
    # Comparing semantic inventory permits whitespace differences from an earlier discovery.
    path = root / "inventory.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != inventory:
        raise ValueError("Pinned HF inventory changed")
    if not path.exists():
        immutable_write(path, (json.dumps(inventory, indent=2) + "\n").encode())
    for name in ("files.txt", "README.md", "FIREBALL.py"):
        data, _ = get(
            f"https://huggingface.co/datasets/lara-martin/FIREBALL/resolve/{HF_REVISION}/{name}"
        )
        expected = next(e for e in entries if e["path"] == name)
        if (
            hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            != expected["oid"]
        ):
            raise ValueError("Pinned HF metadata digest differs")
        immutable_write(root / name, data)
    for repo, revision in GITHUB_REVISIONS.items():
        data, _ = get(
            f"https://api.github.com/repos/zhudotexe/{repo}/git/trees/{revision}?recursive=1"
        )
        tree = json.loads(data)
        if tree.get("truncated") or tree["sha"] != revision:
            raise ValueError("Incomplete or changed pinned GitHub tree")
        tree_path = root / (repo + "-tree.json")
        value = {"revision": revision, "tree": tree}
        if tree_path.exists() and json.loads(tree_path.read_text(encoding="utf-8")) != value:
            raise ValueError("Pinned GitHub inventory differs")
        if not tree_path.exists():
            immutable_write(tree_path, json.dumps(value, indent=2).encode())
        for entry in tree["tree"]:
            name = entry["path"]
            if entry["type"] != "blob" or not (
                name.endswith((".py", ".md", ".txt", ".jsonl")) or Path(name).name == "LICENSE"
            ):
                continue
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe upstream path")
            dest = root / "primary" / repo / relative
            data = (
                dest.read_bytes()
                if dest.exists()
                else get(f"https://raw.githubusercontent.com/zhudotexe/{repo}/{revision}/{name}")[0]
            )
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != entry["sha"]:
                raise ValueError("Pinned primary source digest differs: " + name)
            immutable_write(dest, data)
    return {"revision": HF_REVISION, "pages": pages, "entries": len(entries)}


def probe_raw(root):
    """Save bounded HEAD and GET evidence; never treat a partial response as the raw release."""
    outcomes = []
    for method in ("HEAD", "GET"):
        item = {"url": RAW_URL, "method": method, "range": "bytes=0-0" if method == "GET" else None}
        try:
            with urlopen(
                Request(RAW_URL, method=method, headers={"Range": "bytes=0-0"}), timeout=45
            ) as r:
                item.update(
                    status=r.status,
                    content_length=r.headers.get("Content-Length"),
                    content_range=r.headers.get("Content-Range"),
                )
                if method == "GET":
                    item["probe_bytes"] = len(r.read(1))
        except HTTPError as error:
            item.update(status=error.code, error="HTTPError")
        except OSError as error:
            item.update(error=type(error).__name__, message=str(error))
        outcomes.append(item)
    path = Path(root) / "raw-access-probes.json"
    # A dated run is independent evidence; do not replace previous probes.
    if path.exists():
        raise ValueError("Probe evidence exists; retain it or choose a new output root")
    path.write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8")
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--probe-raw", action="store_true")
    args = parser.parse_args()
    print(json.dumps(probe_raw(args.root) if args.probe_raw else discover(args.root), indent=2))


if __name__ == "__main__":
    main()
