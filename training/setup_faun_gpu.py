"""Portable owner-run GPU environment. No rent, credentials, or implicit weight downloads."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from training.hardware_preflight import collect

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "LICENSES_AND_ATTRIBUTIONS.md",
    "docs/intelligent_gm/TRAINING_TRANSFER.md",
    "docs/intelligent_gm/GPU_FAUN_WORKFLOW.md",
    "docs/intelligent_gm/TRAINING_DATA_V3.md",
    "docs/intelligent_gm/TRAINING_DATA_V4.md",
    "docs/intelligent_gm/QLORA_DATA_READY.md",
    "docs/intelligent_gm/FIREBALL.md",
    "docs/intelligent_gm/FIREBALL_COMPLETE.md",
    "docs/intelligent_gm/FIREBALL_RAW.md",
    "docs/intelligent_gm/SOURCE_DATA_V5.md",
    "training/__init__.py",
    "training/train_lora.py",
    "training/tokenize_dataset.py",
    "training/check_faun_data.py",
    "training/fetch_faun_tokenizer.py",
    "training/requirements-faun-cpu.in",
    "training/requirements-faun-cpu.lock",
    "training/synthetic_corpus.py",
    "training/owner_policy.py",
    "training/jsonio.py",
    "training/grounded_curriculum.py",
    "training/fireball.py",
    "training/fireball_archive.py",
    "training/fireball_discover.py",
    "training/fireball_observations.py",
    "training/fireball_audit.py",
    "training/fireball_readiness.py",
    "training/fireball_manifest.py",
    "training/fireball_lineage.py",
    "training/fireball_tasks.py",
    "training/fireball_tokenizer_check.py",
    "training/fireball_materialize.py",
    "training/fireball_verify.py",
    "training/fireball_raw.py",
    "training/fireball_raw_links.py",
    "training/fireball_raw_filtered.py",
    "training/fireball_history_overlay.py",
    "training/fireball_dm_roles.py",
    "training/crd3_source.py",
    "training/gm_mechanics.py",
    "training/audit_gm_coverage.py",
    "training/source_gm_curation.py",
    "training/gm_source_pool.py",
    "training/select_gm_curriculum.py",
    "training/gm_candidate_audit.py",
    "training/gm_research_corpus.py",
    "training/check_gm_research.py",
    "training/gm_review_packet.py",
    "training/gm_review_transfer.py",
    "training/gm_translation.py",
    "training/fetch_translation_models.py",
    "training/requirements-gm-translation.in",
    "training/requirements-gm-translation.lock",
    "training/verify_fireball_history.py",
    "training/grounded_prompt.py",
    "training/rule_curriculum.py",
    "training/grounded_validation.py",
    "training/grounded_workbook.py",
    "training/curriculum/intents-v4.tsv",
    "training/curriculum/parameters-v4.json",
    "training/annotation.py",
    "training/annotation_v2.py",
    "training/scenarios.py",
    "training/xlsx.py",
    "src/rpg_vkr/domain/__init__.py",
    "src/rpg_vkr/domain/character.py",
    "src/rpg_vkr/domain/owner_rules.py",
    "training/model_profiles.py",
    "training/schema.py",
    "training/inspect_archive.py",
    "training/prepare_dataset.py",
    "training/split_dataset.py",
    "training/hardware_preflight.py",
    "training/setup_faun_gpu.py",
    "training/prepare_faun_transfer.py",
    "training/serve.py",
    "training/inference_protocol.py",
    "training/export_model.py",
    "training/merge_gguf.py",
    "training/compare_models.py",
    "training/evaluate_faun.py",
    "training/ollama_probe.py",
    "training/requirements-faun.in",
    "training/requirements-faun-linux.lock",
    "training/configs/faun_qlora_v1.json",
    "src/rpg_vkr/__init__.py",
    "src/rpg_vkr/learning/__init__.py",
    "src/rpg_vkr/learning/quality.py",
    "src/rpg_vkr/narrative/__init__.py",
    "src/rpg_vkr/narrative/local_models.py",
    "src/rpg_vkr/narrative/strategic_critic.py",
)


def bundle(path):
    files = {name: (ROOT / name).read_bytes() for name in FILES}
    manifest = {
        "schema": "faun-training-tools-v1",
        "status": "TOOLS_ONLY_NOT_TRAINED",
        "files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()},
        "weights_included": False,
        "private_data_included": False,
        "training_steps": 0,
    }
    with ZipFile(path, "x", ZIP_DEFLATED) as z:
        for name, value in files.items():
            z.writestr(name, value)
        z.writestr("bundle-manifest.json", json.dumps(manifest, indent=2))
    return manifest


def approve(message):
    if input(message + " [yes/NO]: ").strip().casefold() not in ("yes", "y", "да", "д"):
        raise ValueError("DECLINED: no operation performed")


def record_base(config, *, verify=False):
    from training.model_profiles import validate_local

    validate_local(config)
    root = Path(config["model_path"])
    index = json.loads((root / "model.safetensors.index.json").read_text(encoding="utf-8"))
    hashes = {}
    for name in sorted(set(index["weight_map"].values())):
        if Path(name).name != name or not name.endswith(".safetensors"):
            raise ValueError("Invalid Safetensors shard name")
        h = hashlib.sha256()
        with (root / name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        hashes[name] = h.hexdigest()
    result = {"revision": config["revision"], "weight_sha256": hashes}
    path = root / "base-provenance.json"
    if verify:
        if json.loads(path.read_text(encoding="utf-8")) != result:
            raise ValueError("Existing source weights changed")
    else:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path)
    p.add_argument("--install-stack", action="store_true")
    p.add_argument("--download-base", action="store_true")
    p.add_argument("--environment", type=Path, default=Path(".venv-faun"))
    a = p.parse_args()
    if a.bundle:
        print(json.dumps({"status": bundle(a.bundle)["status"], "training_steps": 0}))
        return
    hardware = collect(scope="friend_gpu")
    if not hardware["gpus"] or max(g["vram_mib"] for g in hardware["gpus"]) < 16 * 1024:
        print(json.dumps({"status": "BLOCKED_HARDWARE", "hardware": hardware, "training_steps": 0}))
        return
    python = a.environment.resolve() / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    if a.install_stack:
        if not sys.platform.startswith("linux"):
            raise ValueError(
                "Use the pinned Linux environment under Linux/WSL2; Windows "
                "drivers are not modified"
            )
        approve(
            "Create a separate environment and download the pinned "
            "candidate training stack (several GB)?"
        )
        if not python.is_file():
            subprocess.run([sys.executable, "-m", "venv", str(a.environment)], check=True)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(ROOT / "training/requirements-faun-linux.lock"),
            ],
            check=True,
        )
        with (a.environment / f"installed-versions-{time.time_ns()}.txt").open(
            "x", encoding="utf-8"
        ) as out:
            subprocess.run([str(python), "-m", "pip", "freeze"], stdout=out, check=True)
    if a.download_base:
        if not python.is_file():
            raise ValueError("Set up the separate training environment first")
        subprocess.run(
            [
                str(python),
                "-c",
                "import torch; from training.model_profiles import validate_faun_cuda; "
                "validate_faun_cuda(torch)",
            ],
            cwd=ROOT,
            check=True,
        )
        config = json.loads(
            (ROOT / "training/configs/faun_qlora_v1.json").read_text(encoding="utf-8")
        )
        config["model_path"] = str(ROOT / config["model_path"])
        destination = ROOT / config["model_path"]
        if (destination / "base-provenance.json").is_file():
            saved = json.loads((destination / "base-provenance.json").read_text(encoding="utf-8"))
            if saved.get("revision") == config["revision"]:
                record_base(config, verify=True)
                print("Pinned base already recorded. No repeated download.")
                return
            raise ValueError("Existing model revision differs; choose a new directory")
        approve(
            "Download original Safetensors Faun weights (~24GB plus "
            "cache) from the pinned public revision?"
        )
        if hardware["free_disk_bytes"] < 60 * 1024**3:
            raise ValueError(
                "BLOCKED_HARDWARE: at least60GiB free disk required for source weights/cache"
            )
        code = (
            "import json;from pathlib import Path;from huggingface_hub import snapshot_download;"
            "c=json.loads(Path('training/configs/faun_qlora_v1.json').read_text(encoding='utf-8'));"
            "snapshot_download(c['model_id'],revision=c['revision'],local_dir=c['model_path'],"
            "allow_patterns=['*.json','*.jinja','*.safetensors']);"
            "from training.model_profiles import validate_local;validate_local(c);"
            "from training.setup_faun_gpu import record_base;record_base(c)"
        )
        subprocess.run([str(python), "-c", code], cwd=ROOT, check=True)
    print(
        "Environment preparation only. Run reviewed-data preflight, "
        "then smoke-test. Training steps: 0."
    )


if __name__ == "__main__":
    main()
