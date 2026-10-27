"""Real optional PEFT training; prerequisites first, never download a model implicitly."""

import argparse
import hashlib
import json
from pathlib import Path

from training.schema import validate


def preflight(config):
    data = Path(config["dataset"])
    base = Path(config["model_path"])
    if not (data / "manifest.json").is_file():
        return "BLOCKED_DATA: no reviewed training dataset"
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "READY" or manifest["sha256"] != config["dataset_sha256"]:
        return "BLOCKED_DATA: unapproved or changed dataset"
    if not config.get("revision") or not config.get("license") or not base.is_dir():
        return "BLOCKED_MODEL: local reviewed base model missing"
    try:
        import torch

        if not torch.cuda.is_available():
            return "BLOCKED_HARDWARE: NVIDIA CUDA required for this QLoRA configuration"
    except ImportError:
        return "BLOCKED_HARDWARE: separate training stack unavailable"
    return "READY"


def train(config, *, smoke=False):
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

    output = Path(config["output"])
    if output.exists():
        raise ValueError("Choose a new output run directory")
    rows = [
        json.loads(line)
        for line in (Path(config["dataset"]) / "train.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    if not rows or not all(validate(row)[0] for row in rows):
        raise ValueError("Invalid training samples")
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_path"], local_files_only=True, trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        config["model_path"],
        local_files_only=True,
        trust_remote_code=False,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16
        ),
        device_map={"": 0},
    )
    model = prepare_model_for_kbit_training(model)
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
    encoded = []
    for row in rows:
        prompt = json.dumps(
            {
                "context": row["public_context"],
                "player": row["player_message"],
                "receipt": row["engine_receipt"],
            },
            ensure_ascii=False,
        )
        prefix = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        answer = tokenizer(row["assistant_reply"], add_special_tokens=False)["input_ids"] + [
            tokenizer.eos_token_id
        ]
        if len(prefix) + len(answer) > config["max_length"]:
            continue
        encoded.append(
            {
                "input_ids": prefix + answer,
                "attention_mask": [1] * (len(prefix) + len(answer)),
                "labels": [-100] * len(prefix) + answer,
            }
        )
    if not encoded:
        raise ValueError("No samples fit the context; nothing trained")
    args = TrainingArguments(
        output_dir=str(output),
        max_steps=2 if smoke else -1,
        num_train_epochs=config["epochs"],
        per_device_train_batch_size=config["batch_size"],
        gradient_accumulation_steps=1 if smoke else config["gradient_accumulation"],
        learning_rate=config["learning_rate"],
        seed=config["seed"],
        bf16=True,
        report_to=[],
        save_strategy="steps",
        save_steps=100,
        logging_steps=1,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
    )
    result = trainer.train()
    model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    adapter = output / "adapter_model.safetensors"
    manifest = {
        "config": config,
        "global_step": trainer.state.global_step,
        "metrics": result.metrics,
        "smoke": smoke,
        "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
        "approved_for_runtime": False,
    }
    (output / "training-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--smoke-test", action="store_true")
    a = p.parse_args()
    config = json.loads(a.config.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {"status": preflight(config), "training_started": False}
            if a.dry_run
            else train(config, smoke=a.smoke_test),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
