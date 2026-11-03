"""Model-specific chat and architecture checks without network or weight loading."""

import hashlib
import json
from pathlib import Path


def template_arguments(config):
    # Keep legacy Qwen behavior; Faun's ChatML template has no thinking control.
    return {} if config.get("model_family") == "faun_mistral_nemo" else {"enable_thinking": False}


def validate_local(config):
    if config.get("model_family") != "faun_mistral_nemo":
        return
    root = Path(config["model_path"])
    data = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if (
        data.get("model_type") != "mistral"
        or data.get("hidden_size") != 5120
        or data.get("num_hidden_layers") != 40
        or data.get("vocab_size") != 131074
    ):
        raise ValueError("BLOCKED_MODEL: Faun architecture differs from pinned metadata")
    template = root / "chat_template.jinja"
    if (
        not template.is_file()
        or hashlib.sha256(template.read_bytes()).hexdigest() != config["chat_template_sha256"]
    ):
        raise ValueError("BLOCKED_MODEL: Faun chat template missing or changed")
    if not (root / "model.safetensors.index.json").is_file():
        raise ValueError("BLOCKED_MODEL: original Safetensors required, GGUF cannot be trained")


def validate_lora_modules(model, config):
    requested = set(config["target_modules"])
    found = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    if not requested <= found:
        raise ValueError("BLOCKED_MODEL: requested LoRA layers are missing")
