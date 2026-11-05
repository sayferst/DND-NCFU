"""Download four pinned public tokenizer/metadata files (~17MB), never weights."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

MODEL = "limloop/MN-12B-Faun-RP-RU"
REVISION = "bdfc761b14feb9dd03ef158a4d337fc1cf5fd183"
HASHES = {
    "tokenizer.json": "a2fa2956478eaa353c6c4b1f47fdd6868cce6075e52e169c35ae8bd28524e7a8",
    "tokenizer_config.json": "b293a4a227fc6040146b045de07dd99978d58424be0d59c10277217753d159d5",
    "chat_template.jinja": "99000004eb5936e12e2cb9ba6449b7d194155b6439e8686f658b15cc71938b0b",
    "config.json": "2edc21d022470a1225b8a6e5a90b8d6f1578999cf8c4873bfd36f5b3e53c5edb",
}


def fetch(output, *, opener=urlopen):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sizes = {}
    for name, expected in HASHES.items():
        limit = 32 * 1024**2 if name == "tokenizer.json" else 128 * 1024
        with opener(
            f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}", timeout=60
        ) as reply:
            raw = reply.read(limit + 1)
        if len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("BLOCKED_MODEL: public tokenizer file size/hash differs: " + name)
        (output / name).write_bytes(raw)
        sizes[name] = len(raw)
    report = {
        "model": MODEL,
        "revision": REVISION,
        "file_sha256": HASHES,
        "bytes": sizes,
        "weights_downloaded": False,
        "private_data_sent": False,
    }
    (output / "download-manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    fetch(a.output)
    print("TOKENIZER_ONLY_DOWNLOADED_NO_WEIGHTS")


if __name__ == "__main__":
    main()
