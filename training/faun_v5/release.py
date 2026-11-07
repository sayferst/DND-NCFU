"""Seal a CPU-verified release and create/inspect a deterministic ZIP64 archive."""

import argparse
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

from training.faun_v5.train import verify_data
from training.faun_v5.validate import SPLITS, fingerprint, rows, sha


def seal(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    cpu = json.loads((root / "reports/tokenization.json").read_text(encoding="utf-8"))
    expected = {"train": 26880, "val": 3360, "test": 3360, "ood_test_only": 500}
    if cpu["status"] != "PASS" or cpu["failure_count"] != 0:
        raise ValueError("CPU audit incomplete")
    for split, count in expected.items():
        current = sha(root / (split + ".jsonl"))
        if cpu["bindings"][split + ".jsonl"] != current:
            raise ValueError("Tokenization report is stale")
        if cpu["splits"][split]["samples"] != count or cpu["splits"][split]["independent"] != count:
            raise ValueError("Missing full independent tokenization")
        if sum(1 for _ in rows(root, split)) != count:
            raise ValueError("Count mismatch")
    for split, name in (("test", "eval_gold"), ("ood_test_only", "ood_eval_gold")):
        gold = {r["id"]: r for r in rows(root, name)}
        for row in rows(root, split):
            item = gold.pop(row["id"])
            if (
                item["messages"] != row["messages"][:-1]
                or item["reference"] != row["messages"][-1]["content"]
                or item["expected_state"] != row["state_after"]
                or item["expected_numbers"] != row["engine_result"]["numbers"]
            ):
                raise ValueError("Evaluation gold mismatch")
        if gold:
            raise ValueError("Extra gold entries")
    if manifest["file_sha256"] != {s: sha(root / (s + ".jsonl")) for s in SPLITS}:
        raise ValueError("Manifest data hashes changed")
    if manifest["data_sha256"] != fingerprint(manifest["file_sha256"]):
        raise ValueError("Dataset fingerprint mismatch")
    manifest["status"] = "READY_FOR_CONTROLLED_QLORA_EXPERIMENT"
    manifest["training_steps"] = 0
    manifest["approved_for_runtime"] = False
    manifest["narrative_review"] = "assistant_sampled_not_full_human_review"
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    hashes = {
        p.relative_to(root).as_posix(): sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and p.name != "sha256_manifest.json"
        and "__pycache__" not in p.parts
        and ".pytest_cache" not in p.parts
        and ".ruff_cache" not in p.parts
    }
    (root / "sha256_manifest.json").write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_data(root)
    return manifest


def archive(root, output):
    root, output = Path(root), Path(output)
    verify_data(root)
    files = json.loads((root / "sha256_manifest.json").read_text())
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in sorted([*files, "sha256_manifest.json"]):
            info = zipfile.ZipInfo(root.name + "/" + name, date_time=(2026, 11, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, (root / name).read_bytes(), compresslevel=6)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP CRC failure")
    return {
        "file": output.name,
        "bytes": output.stat().st_size,
        "sha256": sha(output),
        "payload_files": len(files) + 1,
    }


def extract(archive_path, output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive_path) as z:
        infos = z.infolist()
        if (
            len({i.filename for i in infos}) != len(infos)
            or sum(i.file_size for i in infos) > 2 * 1024**3
        ):
            raise ValueError("Duplicate archive paths or excessive size")
        for info in infos:
            name = PurePosixPath(info.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in info.filename
                or stat.S_ISLNK(info.external_attr >> 16)
                or not name.parts
                or name.parts[0] != "DND_NCFU_FAUN_V5_READY"
            ):
                raise ValueError("Unsafe archive member")
        if z.testzip() is not None:
            raise ValueError("ZIP CRC failure")
        z.extractall(output)
    root = output / "DND_NCFU_FAUN_V5_READY"
    verify_data(root)
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--extract-to", type=Path)
    a = p.parse_args()
    if a.extract_to:
        print(extract(a.archive, a.extract_to))
    elif a.archive:
        print(json.dumps(archive(a.dataset, a.archive), indent=2))
    else:
        print(json.dumps(seal(a.dataset), indent=2))


if __name__ == "__main__":
    main()
