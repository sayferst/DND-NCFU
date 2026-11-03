"""Approved PEFT -> merged local Safetensors -> local llama.cpp Q4_K_M.

No downloads or automatic activation. A dry run checks prerequisites only.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from training.hardware_preflight import collect
from training.model_profiles import validate_local


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(deployment, config, llama_cpp, output):
    record = json.loads(Path(deployment).read_text(encoding="utf-8"))
    evaluation = record.get("evaluation", {})
    if (
        record.get("approved_for_runtime") is not True
        or evaluation.get("approved_by_owner") is not True
        or evaluation.get("critical_regression") is not False
        or evaluation.get("holdout_campaigns", 0) < 1
    ):
        raise ValueError("BLOCKED_APPROVAL: verified owner holdout approval required")
    weights = Path(record["adapter_path"])
    training = json.loads((weights.parent / "training-manifest.json").read_text(encoding="utf-8"))
    if (
        training.get("smoke")
        or training.get("global_step", 0) < 1
        or training.get("checkpoint_reloaded") is not True
        or digest(weights) != record["adapter_sha256"]
        or training.get("model_revision") != config["revision"]
    ):
        raise ValueError("BLOCKED_MODEL: real matching reloaded adapter required")
    validate_local(config)
    llama_cpp = Path(llama_cpp).resolve()
    converter = llama_cpp / "convert_hf_to_gguf.py"
    quantizer = next(
        (
            p
            for p in (
                llama_cpp / "build/bin/llama-quantize",
                llama_cpp / "build/bin/Release/llama-quantize.exe",
                llama_cpp / "llama-quantize.exe",
            )
            if p.is_file()
        ),
        None,
    )
    if not converter.is_file() or quantizer is None:
        raise ValueError("BLOCKED_TOOLS: existing local llama.cpp converter/quantizer required")
    if Path(output).exists():
        raise ValueError("Choose a new output directory")
    hardware = collect(disk_path=Path(output).resolve().parent)
    if (
        hardware["memory"].get("available_bytes", 0) < 40 * 1024**3
        or hardware["free_disk_bytes"] < 64 * 1024**3
    ):
        raise ValueError(
            "BLOCKED_HARDWARE: conservative merge preflight needs 40GiB free RAM/64GiB free disk"
        )
    return weights.parent, converter, quantizer


def export(deployment, config, llama_cpp, output, *, execute=False):
    adapter, converter, quantizer = verify(deployment, config, llama_cpp, output)
    output = Path(output).resolve()
    commands = [
        [
            sys.executable,
            str(converter),
            str(output / "merged"),
            "--outtype",
            "f16",
            "--outfile",
            str(output / "model-f16.gguf"),
        ],
        [
            str(quantizer),
            str(output / "model-f16.gguf"),
            str(output / "model-Q4_K_M.gguf"),
            "Q4_K_M",
        ],
    ]
    if not execute:
        return {"status": "PREFLIGHT_ONLY", "commands": commands, "merged": False}
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    output.mkdir(parents=True, exist_ok=False)
    base = AutoModelForCausalLM.from_pretrained(
        config["model_path"],
        dtype=torch.float16,
        device_map="cpu",
        local_files_only=True,
        trust_remote_code=False,
    )
    model = PeftModel.from_pretrained(base, adapter, local_files_only=True)
    merged = model.merge_and_unload(safe_merge=True)
    merged.save_pretrained(output / "merged", safe_serialization=True)
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_path"], local_files_only=True, trust_remote_code=False
    )
    tokenizer.save_pretrained(output / "merged")
    for command in commands:
        subprocess.run(command, check=True)
    weights = output / "model-Q4_K_M.gguf"
    (output / "Modelfile").write_text("FROM ./model-Q4_K_M.gguf\n", encoding="utf-8")
    result = {
        "status": "EXPORTED_NOT_ACTIVATED",
        "model_revision": config["revision"],
        "gguf_sha256": digest(weights),
        "gguf_bytes": weights.stat().st_size,
        "requires_inference_parity_test": True,
    }
    (output / "export-manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--llama-cpp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(
        json.dumps(
            export(args.deployment, config, args.llama_cpp, args.output, execute=args.execute),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
