"""Real optional PEFT training; prerequisites first, never download a model implicitly."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from training.tokenize_dataset import encode_dataset, verify_cpu_report


def preflight(config):
    data = Path(config["dataset"])
    base = Path(config["model_path"])
    if not (data / "manifest.json").is_file():
        return "BLOCKED_DATA: no reviewed training dataset"
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    if config.get("dataset_policy") == "synthetic-pilot-v1":
        from training.synthetic_corpus import verify

        try:
            verify(data)
        except (ValueError, OSError, KeyError, TypeError):
            return "BLOCKED_DATA: invalid synthetic pilot"
        expected_status = "PILOT_READY"
    elif config.get("dataset_policy") == "grounded-synthetic-v1":
        from training.grounded_validation import verify

        try:
            verify(data)
        except (ValueError, OSError, KeyError, TypeError):
            return "BLOCKED_DATA: invalid grounded synthetic corpus"
        expected_status = "READY_SYNTHETIC"
    else:
        expected_status = "READY"
    if manifest.get("status") != expected_status or manifest.get("sha256") != config.get(
        "dataset_sha256"
    ):
        return "BLOCKED_DATA: unapproved or changed dataset"
    if config.get("model_family") == "faun_mistral_nemo":
        hashes = manifest.get("file_sha256", {})
        for split in ("train", "val", "test"):
            path = data / (split + ".jsonl")
            if (
                not path.is_file()
                or hashes.get(split) != hashlib.sha256(path.read_bytes()).hexdigest()
            ):
                return "BLOCKED_DATA: actual split hashes missing or changed"
    if config.get("model_family") == "faun_mistral_nemo":
        from training.tokenize_dataset import load_splits

        try:
            load_splits(config)
        except (ValueError, OSError, KeyError, TypeError):
            return "BLOCKED_DATA: invalid samples or holdout separation"
    if not config.get("revision") or not config.get("license") or not base.is_dir():
        return "BLOCKED_MODEL: local reviewed base model missing"
    from training.model_profiles import validate_local

    try:
        validate_local(config)
    except (ValueError, OSError, KeyError) as error:
        return "BLOCKED_MODEL: " + type(error).__name__
    try:
        import torch

        if config.get("model_family") == "faun_mistral_nemo":
            from training.model_profiles import validate_faun_cuda

            try:
                validate_faun_cuda(torch)
            except ValueError as error:
                return str(error)
        if not torch.cuda.is_available():
            return "BLOCKED_HARDWARE: NVIDIA CUDA required for this QLoRA configuration"
        if config.get("precision", "bf16") == "bf16" and not torch.cuda.is_bf16_supported():
            return "BLOCKED_HARDWARE: configured BF16 is unsupported"
    except ImportError:
        return "BLOCKED_HARDWARE: separate training stack unavailable"
    return "READY"


def run_signature(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def validate_resume(config, checkpoint, *, smoke=None):
    output = Path(config["output"]).resolve()
    checkpoint = Path(checkpoint).resolve()
    if checkpoint.parent != output or not re.fullmatch(r"checkpoint-[0-9]+", checkpoint.name):
        raise ValueError("Checkpoint must belong to this run directory")
    provenance = json.loads((output / "run-provenance.json").read_text(encoding="utf-8"))
    state = json.loads((checkpoint / "trainer_state.json").read_text(encoding="utf-8"))
    if provenance.get("config_sha256") != run_signature(config) or state.get("global_step", 0) < 1:
        raise ValueError("Changed run configuration or checkpoint without actual steps")
    if smoke is not None and provenance.get("smoke") is not smoke:
        raise ValueError("Cannot change smoke/full mode when resuming")
    return str(checkpoint)


def smoke_samples(rows):
    """Exercise the longest real sequence and a typical one without using test data."""
    ordered = sorted(rows, key=lambda row: len(row["input_ids"]))
    if not ordered:
        raise ValueError("Cannot smoke-test an empty split")
    return [ordered[-1]] if len(ordered) == 1 else [ordered[-1], ordered[(len(ordered) - 1) // 2]]


def validate_losses(logs):
    """Fail rather than hide a NaN/Inf training or evaluation loss in a paid run."""
    for key, value in logs.items():
        if "loss" in key and isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(
                "Non-finite loss; stop and inspect the run before spending more GPU time"
            )


def train(config, *, smoke=False, resume=None):
    status = preflight(config)
    if status != "READY":
        raise ValueError(status)
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    from training.model_profiles import validate_lora_modules

    output = Path(config["output"])
    if resume:
        resume = validate_resume(config, resume, smoke=smoke)
    elif output.exists():
        raise ValueError("Choose a new output run directory")
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_path"], local_files_only=True, trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    # All splits are validated and encoded before allocating any model weights.
    parts, token_report = encode_dataset(config, tokenizer)
    verify_cpu_report(config, token_report)
    if config.get("model_family") == "faun_mistral_nemo":
        from training.tokenize_dataset import PinnedFaunTokenizer

        _, backend_report = encode_dataset(
            config, PinnedFaunTokenizer(config["model_path"], config)
        )
        if backend_report["splits"] != token_report["splits"]:
            raise ValueError("BLOCKED_DATA: CPU backend and AutoTokenizer disagree")
    encoded = parts["train"]
    validation = parts["val"]
    if smoke:
        encoded = smoke_samples(encoded)
        validation = smoke_samples(validation)
    model = AutoModelForCausalLM.from_pretrained(
        config["model_path"],
        local_files_only=True,
        trust_remote_code=False,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=config.get("double_quant", False),
        ),
        device_map={"": 0},
    )
    validate_lora_modules(model, config)
    model = prepare_model_for_kbit_training(model)
    if config.get("gradient_checkpointing"):
        model.gradient_checkpointing_enable()
        model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            r=config["lora_r"],
            lora_alpha=config["lora_alpha"],
            lora_dropout=config["lora_dropout"],
            target_modules=config["target_modules"],
            task_type="CAUSAL_LM",
        ),
    )
    args = TrainingArguments(
        output_dir=str(output),
        max_steps=2 if smoke else -1,
        num_train_epochs=config["epochs"],
        per_device_train_batch_size=config["batch_size"],
        per_device_eval_batch_size=1,
        prediction_loss_only=True,
        logging_nan_inf_filter=False,
        gradient_accumulation_steps=1 if smoke else config["gradient_accumulation"],
        learning_rate=config["learning_rate"],
        seed=config["seed"],
        bf16=True,
        report_to=[],
        save_strategy="steps",
        save_steps=1 if smoke else config.get("save_steps", 25),
        save_total_limit=2,
        logging_steps=1,
        eval_strategy="steps" if smoke else "epoch",
        eval_steps=1 if smoke else None,
    )

    from transformers import TrainerCallback

    class FiniteLoss(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            validate_losses(logs or {})

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            validate_losses(metrics or {})

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded,
        eval_dataset=validation,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
        callbacks=[FiniteLoss()],
    )
    if not resume:
        output.mkdir(parents=True, exist_ok=True)
        (output / "run-provenance.json").write_text(
            json.dumps(
                {"config_sha256": run_signature(config), "training_started": True, "smoke": smoke}
            ),
            encoding="utf-8",
        )
    result = trainer.train(resume_from_checkpoint=resume)
    validate_losses(result.metrics)
    model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    model.load_adapter(output, adapter_name="reload_check", is_trainable=False)
    model.delete_adapter("reload_check")
    adapter = output / "adapter_model.safetensors"
    manifest = {
        "config": config,
        "global_step": trainer.state.global_step,
        "metrics": result.metrics,
        "smoke": smoke,
        "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
        "approved_for_runtime": False,
        "adapter_reloaded": True,
        "checkpoint_reloaded": bool(resume),
        "resumed_from": resume,
        "model_revision": config["revision"],
        "training_examples": len(encoded),
        "validation_examples": len(parts["val"]),
        "test_examples_used_for_training": 0,
        "dataset_policy": config.get("dataset_policy", "gm-sft-v1"),
        "tokenization": token_report,
        "max_vram_allocated_bytes": torch.cuda.max_memory_allocated(0),
        "max_vram_reserved_bytes": torch.cuda.max_memory_reserved(0),
        "hardware": {
            "gpu": torch.cuda.get_device_name(0),
            "vram_bytes": torch.cuda.get_device_properties(0).total_memory,
        },
    }
    (output / "training-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--resume-from-checkpoint", type=Path)
    a = p.parse_args()
    config = json.loads(a.config.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {"status": preflight(config), "training_started": False}
            if a.dry_run
            else train(config, smoke=a.smoke_test, resume=a.resume_from_checkpoint),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
