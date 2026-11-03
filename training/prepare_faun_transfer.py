"""Offline transfer package: tools and configs only, never weights or user datasets."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from training.setup_faun_gpu import ROOT, bundle

GUIDE = """# Faun QLoRA transfer

Extract this entire archive into a new folder on the authorized GPU computer.
Use Linux/WSL2 x86_64 and Python3.12. The game GGUF remains on the Acer.
This archive contains no weights, datasets, keys or completed training results.
No cloud rental is performed.16GiB VRAM is a preliminary minimum, not a fit guarantee.
Prefer24GiB or more. CUDA device0 must support BF16. Select a card using
CUDA_VISIBLE_DEVICES before launching Python if the machine has multiple GPUs.

1. Read-only diagnosis:
   python3.12 -m training.hardware_preflight --scope friend_gpu --output hardware-001.json
2. Separate environment (explicit confirmation, several GB of dependencies):
   python3.12 -m training.setup_faun_gpu --install-stack
3. Original pinned Safetensors (explicit confirmation, about24GB;60GiB free disk):
   python3.12 -m training.setup_faun_gpu --download-base
4. Separately transfer only permitted, privacy-reviewed data. Prepare it at
   data/processed/gm-sft-v1 using training.prepare_dataset. Excel action labels
   alone are not narrator SFT: SFT requires checked replies and real receipts.
5. Rebuild a NEW transfer archive with --dataset pointing at that prepared folder
   to bind dataset SHA, or bind the matching manifest SHA in your config copies.
   Data is NEVER copied into this archive automatically.
6. Run only when reviewed data, original base and CUDA are ready:
   .venv-faun/bin/python -m training.train_lora --config faun-smoke.json --dry-run
   .venv-faun/bin/python -m training.train_lora --config faun-smoke.json --smoke-test
   Inspect actual loss, global_step2, adapter and reload before the full run:
   .venv-faun/bin/python -m training.train_lora --config faun-full.json
   Resume with the SAME config and a real checkpoint under its output directory:
   Add --resume-from-checkpoint artifacts/faun-full/checkpoint-100 to the full command.
7. Independently evaluate using training.evaluate_faun on test campaigns.
   Human review is required before training.export_model / training.merge_gguf.
   Deployment is not automatic. QLoRA does not guarantee faster CPU inference.

Default configs remain BLOCKED_DATA until the dataset is approved and bound.
A successful package creation is NOT a training step. Original Safetensors stay
frozen during QLoRA; only the LoRA adapter is optimized. Keep the game GGUF as
baseline. Never put API keys, private saves or unapproved dialogues in the ZIP.
"""


def prepare(output, *, dataset=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a new transfer archive; existing files are preserved")
    config = json.loads((ROOT / "training/configs/faun_qlora_v1.json").read_text(encoding="utf-8"))
    data_status, data_sha = "BLOCKED_DATA", None
    if dataset is not None:
        from training.evaluate_faun import holdout

        manifest, _ = holdout(dataset)
        data_status, data_sha = "REVIEWED_DATA_HASH_BOUND_NOT_INCLUDED", manifest["sha256"]
    config["dataset_sha256"] = data_sha
    config["dataset"] = "data/processed/gm-sft-v1"
    config["model_path"] = "models/faun-reviewed-base"
    files = {}
    with tempfile.TemporaryDirectory(prefix="faun-transfer-") as folder:
        tools_zip = Path(folder) / "tools.zip"
        bundle(tools_zip)
        with ZipFile(tools_zip) as source:
            for name in source.namelist():
                files[name] = source.read(name)
    for stage in ("smoke", "full"):
        value = config | {"output": "artifacts/faun-" + stage}
        files["faun-" + stage + ".json"] = json.dumps(value, indent=2).encode()
    files["START_HERE.md"] = GUIDE.encode()
    manifest = {
        "schema": "faun-transfer-v1",
        "status": "TOOLS_PREPARED_NOT_TRAINED",
        "dataset_status": data_status,
        "dataset_sha256": data_sha,
        "base_model_id": config["model_id"],
        "base_revision": config["revision"],
        "weights_included": False,
        "dataset_included": False,
        "game_gguf_needed_on_gpu": False,
        "training_steps": 0,
        "files_sha256": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()},
    }
    files["transfer-manifest.json"] = json.dumps(manifest, indent=2).encode()
    with ZipFile(output, "x", ZIP_DEFLATED) as dest:
        for name, raw in files.items():
            dest.writestr(name, raw)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    report = prepare(args.output, dataset=args.dataset)
    print(json.dumps({k: v for k, v in report.items() if k != "files_sha256"}, indent=2))


if __name__ == "__main__":
    main()
