"""Optional real V5 PEFT trainer. Dry-run never imports torch or fetches weights."""

import argparse
import json
import math
from pathlib import Path

from training.faun_v5.tokenize import encode
from training.faun_v5.validate import fingerprint, rows, sha
from training.fetch_faun_tokenizer import HASHES, MODEL, REVISION

DEFAULTS = {
    "base_model": MODEL,
    "revision": REVISION,
    "max_length": 4000,
    "epochs": 5,
    "batch_size": 1,
    "gradient_accumulation_steps": 16,
    "learning_rate": 5e-5,
    "seed": 37,
    "lora_r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "double_quant": True,
}


def read_config(path):
    path = Path(path).resolve()
    c = json.loads(path.read_text(encoding="utf-8"))
    if set(c) != set(DEFAULTS) | {"dataset", "model_path", "output"}:
        raise ValueError("Unknown or missing config options")
    if (
        not isinstance(c["epochs"], int)
        or not 1 <= c["epochs"] <= 5
        or any(c[k] != v for k, v in DEFAULTS.items() if k != "epochs")
    ):
        raise ValueError("Configuration differs from reviewed V5 profile")
    for key in ("dataset", "model_path", "output"):
        c[key] = str((path.parent / c[key]).resolve())
    return c


def verify_data(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "READY_FOR_CONTROLLED_QLORA_EXPERIMENT":
        raise ValueError("Unreleased dataset")
    checksums = json.loads((root / "sha256_manifest.json").read_text(encoding="utf-8"))
    for name, expected in checksums.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or sha(root / path) != expected:
            raise ValueError("Release file changed: " + name)
    cpu = json.loads((root / "reports/tokenization.json").read_text(encoding="utf-8"))
    if cpu["status"] != "PASS" or cpu["failure_count"] or cpu["max_length"] != 4000:
        raise ValueError("CPU audit failed")
    for name, expected in cpu["bindings"].items():
        if sha(root / name) != expected:
            raise ValueError("CPU report is stale")
    if any(
        cpu["splits"][s]["independent"] != manifest["splits"][s] for s in ("train", "val", "test")
    ):
        raise ValueError("Independent full tokenization missing")
    return manifest, cpu


def verify_base(root):
    root = Path(root)
    pinned = json.loads(Path(__file__).with_name("base_model_manifest.json").read_text())
    if pinned["repository"] != MODEL or pinned["revision"] != REVISION:
        raise ValueError("Base metadata changed")
    for name, expected in HASHES.items():
        if sha(root / name) != expected:
            raise ValueError("Wrong base tokenizer/config: " + name)
    shards = {f["path"]: f for f in pinned["files"] if f["path"].endswith(".safetensors")}
    mapping = json.loads((root / "model.safetensors.index.json").read_text())["weight_map"]
    if set(mapping.values()) != set(shards):
        raise ValueError("Shard index does not describe pinned base")
    for name, entry in shards.items():
        if (root / name).stat().st_size != entry["size"] or sha(root / name) != entry["sha256"]:
            raise ValueError("Wrong base weights: " + name)
    return fingerprint(pinned)


def finite(metrics):
    if any(
        "loss" in k and isinstance(v, (float, int)) and not math.isfinite(v)
        for k, v in metrics.items()
    ):
        raise ValueError("Non-finite loss; stop experiment")


def check_resume(output, checkpoint, provenance):
    output, checkpoint = Path(output).resolve(), Path(checkpoint).resolve()
    if checkpoint.parent != output or not checkpoint.name.startswith("checkpoint-"):
        raise ValueError("Resume checkpoint must belong to this output directory")
    recorded = json.loads((output / "run-provenance.json").read_text())
    if recorded != provenance:
        raise ValueError("Changed data/model/config or smoke/full mode")
    for name in ("trainer_state.json", "optimizer.pt", "scheduler.pt", "adapter_model.safetensors"):
        if not (checkpoint / name).is_file():
            raise ValueError("Incomplete resume checkpoint: " + name)
    if not list(checkpoint.glob("rng_state*.pth")):
        raise ValueError("Resume RNG state missing")
    return str(checkpoint)


def train(c, *, smoke=False, resume=None):
    manifest, cpu = verify_data(c["dataset"])
    base_hash = verify_base(c["model_path"])
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        EarlyStoppingCallback,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        set_seed,
    )

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("NVIDIA CUDA with BF16 required")
    output = Path(c["output"])
    provenance = {
        "config": c,
        "dataset": manifest["data_sha256"],
        "base": base_hash,
        "smoke": smoke,
    }
    if resume:
        resume = check_resume(output, resume, provenance)
    elif output.exists():
        raise ValueError("New experiment requires a new output directory")
    tokenizer = AutoTokenizer.from_pretrained(
        c["model_path"], local_files_only=True, trust_remote_code=False
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    encoded = {}
    for split in ("train", "val"):
        items = [
            encode(tokenizer, r["messages"], c["max_length"])[0] for r in rows(c["dataset"], split)
        ]
        if len(items) != cpu["splits"][split]["samples"]:
            raise ValueError("Tokenization count changed")
        current_hash = fingerprint(items)
        if current_hash != cpu["splits"][split]["encoded_sha256"]:
            raise ValueError("Training tokenizer differs from CPU proof")
        encoded[split] = items
    if smoke:
        # Real longest train/validation sequences, batch1, same grad accumulation.
        encoded = {
            k: sorted(v, key=lambda x: len(x["input_ids"]), reverse=True)[:16]
            for k, v in encoded.items()
        }
    set_seed(c["seed"])
    torch.cuda.reset_peak_memory_stats()
    model = AutoModelForCausalLM.from_pretrained(
        c["model_path"],
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        device_map={"": 0},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        ),
    )
    available = {n.rsplit(".", 1)[-1] for n, _ in model.named_modules()}
    if not set(c["target_modules"]) <= available:
        raise ValueError("LoRA projection module missing")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            r=c["lora_r"],
            lora_alpha=c["lora_alpha"],
            lora_dropout=c["lora_dropout"],
            target_modules=c["target_modules"],
            task_type="CAUSAL_LM",
        ),
    )

    class Finite(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            finite(logs or {})

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            finite(metrics or {})

    args = TrainingArguments(
        output_dir=str(output),
        num_train_epochs=1 if smoke else c["epochs"],
        max_steps=2 if smoke else -1,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=c["gradient_accumulation_steps"],
        learning_rate=c["learning_rate"],
        seed=c["seed"],
        data_seed=c["seed"],
        bf16=True,
        gradient_checkpointing=True,
        prediction_loss_only=True,
        eval_strategy="steps" if smoke else "epoch",
        eval_steps=1 if smoke else None,
        save_strategy="steps" if smoke else "epoch",
        save_steps=1,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=1,
        logging_nan_inf_filter=False,
        report_to=[],
        optim="paged_adamw_8bit",
        warmup_ratio=0.03,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded["train"],
        eval_dataset=encoded["val"],
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
        callbacks=[Finite(), EarlyStoppingCallback(early_stopping_patience=1)],
    )
    if not resume:
        output.mkdir(parents=True, exist_ok=True)
        (output / "run-provenance.json").write_text(
            json.dumps(provenance, indent=2), encoding="utf-8"
        )
    result = trainer.train(resume_from_checkpoint=resume)
    finite(result.metrics)
    trainer.save_state()
    model.save_pretrained(output / "best_adapter", safe_serialization=True)
    tokenizer.save_pretrained(output / "best_adapter")
    report = {
        "metrics": result.metrics,
        "global_step": trainer.state.global_step,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_eval_loss": trainer.state.best_metric,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "adapter_sha256": sha(output / "best_adapter/adapter_model.safetensors"),
        "gpu": torch.cuda.get_device_name(),
        "smoke": smoke,
        "approved_for_runtime": False,
        "test_examples_used_for_training": 0,
    }
    (output / "training-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--resume", type=Path)
    a = p.parse_args()
    c = read_config(a.config)
    if a.dry_run:
        verify_data(c["dataset"])
        try:
            verify_base(c["model_path"])
        except (OSError, ValueError) as error:
            print(
                json.dumps(
                    {"status": "BLOCKED_LOCAL_BASE", "detail": str(error), "gpu_started": False}
                )
            )
            return
        print(json.dumps({"status": "DATA_AND_BASE_VERIFIED_GPU_NOT_TESTED", "gpu_started": False}))
    else:
        print(json.dumps(train(c, smoke=a.smoke_test, resume=a.resume), indent=2))


if __name__ == "__main__":
    main()
