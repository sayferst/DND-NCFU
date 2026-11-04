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
4. Separately transfer selected, reviewed data. Real episodes use gm-sft-v1
   and training.prepare_dataset. An explicitly permitted synthetic pilot uses
   data/processed/gm-synthetic-pilot-v1 and its distinct manifest/provenance.
   Excel action labels alone are not narrator SFT.
5. Rebuild a NEW transfer archive with --dataset to bind its SHA. Synthetic
   pilots also require --synthetic-pilot --cpu-report REPORT.json. Put that
   unchanged report beside the dataset manifest as cpu-tokenization.json.
   Data and CPU reports are NEVER copied into this tools archive automatically.
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

Synthetic pilot mode is a separate explicit policy. It creates faun-pilot.json
instead of faun-full.json and requires a bound CPU tokenization report. Copy
that report separately to the configured dataset directory as cpu-tokenization.json.
A 40-example synthetic pilot checks the pipeline, not full game-master quality.
Its examples are editorially reviewed by an assistant, not by a human. Use a
new GPU pilot output directory after the two-step smoke. Test examples remain
excluded from gradient updates. Read docs/intelligent_gm/TRAINING_DATA_V3.md.

Default configs remain BLOCKED_DATA until the dataset is approved and bound.
A successful package creation is NOT a training step. Original Safetensors stay
frozen during QLoRA; only the LoRA adapter is optimized. Keep the game GGUF as
baseline. Never put API keys, private saves or unapproved dialogues in the ZIP.
"""


GUIDE += """
Before downloading weights or renting GPU time, check the separately transferred
data with standard-library Python from the extracted transfer root:
  python3.12 -m training.check_faun_data --config faun-smoke.json --output integrity-001.json
This does not rerun tokenization. With the optional local CPU tokenizer stack:
  USE_TORCH=0 .venv-faun-cpu/bin/python -m training.check_faun_data --config faun-smoke.json \\
    --tokenizer tokenizer --independent --output tokenization-001.json
Read docs/intelligent_gm/QLORA_DATA_READY.md for exact readiness and holdout limits.

V4 full grounded synthetic mode (--grounded-synthetic) is distinct from the old
40-pair pilot. It creates faun-smoke.json and faun-full.json; place the separately
authorized corpus under data/processed/gm-grounded-synthetic-v1 and its bound
CPU report at cpu-tokenization.json in that directory. Read TRAINING_DATA_V4.md.
The complete private delivery includes those authorized data separately; this
tools-only archive never adds them automatically. Public curriculum definition
tables are code inputs included in the tools, not private played campaigns.
"""


def prepare(
    output,
    *,
    dataset=None,
    synthetic_pilot=False,
    grounded_synthetic=False,
    fireball_augmented=False,
    cpu_report=None,
):
    if sum((synthetic_pilot, grounded_synthetic, fireball_augmented)) > 1:
        raise ValueError("Choose one explicit synthetic corpus policy")
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a new transfer archive; existing files are preserved")
    config = json.loads((ROOT / "training/configs/faun_qlora_v1.json").read_text(encoding="utf-8"))
    data_status, data_sha = "BLOCKED_DATA", None
    if dataset is not None:
        if fireball_augmented:
            from training.fireball import verify

            manifest, _ = verify(dataset)
            data_status = "FIREBALL_AUGMENTED_HASH_BOUND_NOT_INCLUDED"
            config["dataset_policy"] = "fireball-augmented-v1"
        elif grounded_synthetic:
            from training.grounded_validation import verify

            manifest, _ = verify(dataset)
            data_status = "GROUNDED_SYNTHETIC_HASH_BOUND_NOT_INCLUDED"
            config["dataset_policy"] = "grounded-synthetic-v1"
        elif synthetic_pilot:
            from training.synthetic_corpus import verify

            manifest, _ = verify(dataset)
            data_status = "SYNTHETIC_PILOT_HASH_BOUND_NOT_INCLUDED"
            config["dataset_policy"] = "synthetic-pilot-v1"
        else:
            from training.evaluate_faun import holdout

            manifest, _ = holdout(dataset)
            data_status = "REVIEWED_DATA_HASH_BOUND_NOT_INCLUDED"
        data_sha = manifest["sha256"]
    elif synthetic_pilot or grounded_synthetic or fireball_augmented:
        raise ValueError("BLOCKED_DATA: --synthetic-pilot requires a prepared dataset")
    config["dataset_sha256"] = data_sha
    config["dataset"] = (
        "data/processed/gm-fireball-augmented-v1"
        if fireball_augmented
        else "data/processed/gm-grounded-synthetic-v1"
        if grounded_synthetic
        else "data/processed/gm-synthetic-pilot-v1"
        if synthetic_pilot
        else "data/processed/gm-sft-v1"
    )
    report_sha = None
    if cpu_report is not None:
        raw = Path(cpu_report).read_bytes()
        report = json.loads(raw)
        if (
            data_sha is None
            or report.get("dataset_sha256") != data_sha
            or report.get("max_length") != config["max_length"]
            or report.get("dropped_samples") != 0
            or report.get("schema") != "faun-cpu-tokenization-v1"
        ):
            raise ValueError("BLOCKED_DATA: CPU report is not bound to this corpus/config")
        report_sha = hashlib.sha256(raw).hexdigest()
        from training.tokenize_dataset import bound_cpu_report

        bound_cpu_report(
            config
            | {
                "cpu_tokenization_report": str(cpu_report),
                "cpu_tokenization_report_sha256": report_sha,
            }
        )
        config["cpu_tokenization_report"] = config["dataset"] + "/cpu-tokenization.json"
        config["cpu_tokenization_report_sha256"] = report_sha
    if (synthetic_pilot or grounded_synthetic or fireball_augmented) and cpu_report is None:
        raise ValueError("BLOCKED_DATA: tokenize the synthetic pilot on CPU first")
    config["model_path"] = "models/faun-reviewed-base"
    files = {}
    with tempfile.TemporaryDirectory(prefix="faun-transfer-") as folder:
        tools_zip = Path(folder) / "tools.zip"
        bundle(tools_zip)
        with ZipFile(tools_zip) as source:
            for name in source.namelist():
                files[name] = source.read(name)
    for stage in ("smoke", "pilot" if synthetic_pilot else "full"):
        value = config | {"output": "artifacts/faun-" + stage}
        if synthetic_pilot:
            value["training_purpose"] = "SYNTHETIC_PIPELINE_PILOT"
        files["faun-" + stage + ".json"] = json.dumps(value, indent=2).encode()
    files["START_HERE.md"] = GUIDE.encode()
    manifest = {
        "schema": "faun-transfer-v1",
        "status": "TOOLS_PREPARED_NOT_TRAINED",
        "dataset_status": data_status,
        "dataset_sha256": data_sha,
        "synthetic_pilot": synthetic_pilot,
        "grounded_synthetic": grounded_synthetic,
        "fireball_augmented": fireball_augmented,
        "cpu_report_sha256": report_sha,
        "cpu_report_included": False,
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
    parser.add_argument("--synthetic-pilot", action="store_true")
    parser.add_argument("--grounded-synthetic", action="store_true")
    parser.add_argument("--fireball-augmented", action="store_true")
    parser.add_argument("--cpu-report", type=Path)
    args = parser.parse_args()
    report = prepare(
        args.output,
        dataset=args.dataset,
        synthetic_pilot=args.synthetic_pilot,
        grounded_synthetic=args.grounded_synthetic,
        fireball_augmented=args.fireball_augmented,
        cpu_report=args.cpu_report,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "files_sha256"}, indent=2))


if __name__ == "__main__":
    main()
