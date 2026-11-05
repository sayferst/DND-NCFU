"""Fetch small, pinned local CPU translation assets; never fetch the 12B game model."""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

MODELS = {
    "en-ru": ("rohanksaxena/opus-mt-en-ru", "3e60bacffde1e346edc65b9d057be7d441872779"),
    "ru-en": ("rohanksaxena/opus-mt-ru-en", "0814e5845ab3be4d38fd3e67b8080923e0940a21"),
}
FILES = {
    "README.md",
    "config.json",
    "model.bin",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def fetch(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "pinned-cpu-translation-assets-v1", "models": {}, "training_steps": 0}
    for direction, (repo, revision) in MODELS.items():
        url = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
        with urlopen(
            Request(url, headers={"User-Agent": "DND-NCFU-research/1.0"}), timeout=45
        ) as response:
            raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("Unexpected translation model metadata size")
        metadata = json.loads(raw)
        if metadata.get("sha") != revision:
            raise ValueError("Translation model revision differs")
        entries = [e for e in metadata["siblings"] if e["rfilename"] in FILES]
        if {e["rfilename"] for e in entries} != FILES:
            raise ValueError("Incomplete translation model metadata")
        if sum(e["size"] for e in entries) > 90 * 1024**2:
            raise ValueError("Translation model exceeds the small-asset budget")
        folder = output / direction
        folder.mkdir(exist_ok=True)
        files = {}
        for entry in entries:
            name = entry["rfilename"]
            dest = folder / name
            size = entry["size"]
            if not dest.exists():
                pending = dest.with_suffix(dest.suffix + ".partial")
                start = pending.stat().st_size if pending.exists() else 0
                headers = {"User-Agent": "DND-NCFU-research/1.0"}
                if start:
                    headers["Range"] = f"bytes={start}-"
                with urlopen(
                    Request(
                        f"https://huggingface.co/{repo}/resolve/{revision}/{name}", headers=headers
                    ),
                    timeout=60,
                ) as response:
                    append = start > 0 and response.status == 206
                    if append and not response.headers.get("Content-Range", "").startswith(
                        f"bytes {start}-"
                    ):
                        raise ValueError("Translation asset resume offset differs")
                    with pending.open("ab" if append else "wb") as stream:
                        while data := response.read(1024 * 1024):
                            if stream.tell() + len(data) > size:
                                raise ValueError("Translation asset larger than pinned metadata")
                            if shutil.disk_usage(output).free - len(data) < 192 * 1024**2:
                                raise OSError("TRANSLATION_ASSET_FREE_SPACE_RESERVE_REACHED")
                            stream.write(data)
                if pending.stat().st_size != size:
                    raise ValueError("Incomplete translation asset; partial retained for resume")
                actual = digest(pending)
                if entry.get("lfs"):
                    valid = actual == entry["lfs"]["sha256"]
                else:
                    valid = (
                        hashlib.sha1(
                            b"blob " + str(size).encode() + b"\0" + pending.read_bytes()
                        ).hexdigest()
                        == entry["blobId"]
                    )
                if not valid:
                    raise ValueError("Translation asset digest differs; partial retained")
                os.rename(pending, dest)
            actual = digest(dest)
            if dest.stat().st_size != size or entry.get("lfs") and actual != entry["lfs"]["sha256"]:
                raise ValueError("Pinned cached translation asset changed")
            if (
                not entry.get("lfs")
                and hashlib.sha1(
                    b"blob " + str(size).encode() + b"\0" + dest.read_bytes()
                ).hexdigest()
                != entry["blobId"]
            ):
                raise ValueError("Pinned translation metadata changed")
            files[name] = {"bytes": size, "sha256": actual}
            print(json.dumps({"direction": direction, "asset": name, "bytes": size}), flush=True)
        manifest["models"][direction] = {
            "repository": repo,
            "revision": revision,
            "source": "Helsinki-NLP/opus-mt-" + direction,
            "license": "CC-BY-4.0",
            "files": files,
        }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fetch(args.output)


if __name__ == "__main__":
    main()
